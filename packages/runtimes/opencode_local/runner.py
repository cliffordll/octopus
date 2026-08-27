from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from pathlib import Path

from ..context_env import apply_runtime_context_env
from ..environment import resolve_runtime_executable
from ..instructions import runtime_prompt_from_config
from ..local_skills import (
    desired_skills_from_config,
    ensure_octopus_cli_shim,
    materialize_runtime_skills,
    prepare_managed_home,
)
from ..local_process import local_process_supervisor
from ..session import effective_resume_session_id
from ..tool_capabilities import (
    append_runtime_tool_guidance,
    append_runtime_workspace_guidance,
)
from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .ollama import LocalOllamaProvider
from .protocol import (
    auth_required,
    build_args,
    first_line,
    model_unavailable,
    parse_jsonl,
    provider,
    string,
    unknown_session,
)


async def execute(context: RuntimeExecutionContext) -> RuntimeExecutionResult:
    command = resolve_runtime_executable(
        string(context.config.get("command")) or "opencode"
    )
    cwd = context.config.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("OpenCode adapter cwd must be a string")
    prompt = append_runtime_workspace_guidance(
        append_runtime_tool_guidance(
            runtime_prompt_from_config(context.config), "opencode_local"
        ),
        context.workspace,
    )
    runtime_config = dict(context.config)
    session_id = await effective_resume_session_id(
        runtime_config,
        cwd,
        runtime_label="OpenCode",
        on_log=context.on_log,
    )
    if session_id is None:
        runtime_config["sessionIdBefore"] = None
        runtime_context = runtime_config.get("_octopus")
        if isinstance(runtime_context, dict):
            runtime_config["_octopus"] = {**runtime_context, "sessionIdBefore": None}
    args = build_args(runtime_config)
    env = dict(os.environ)
    configured_env = context.config.get("env")
    if isinstance(configured_env, dict):
        env.update(
            {
                key: value
                for key, value in configured_env.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        )
    if context.env:
        env.update(context.env)
    local_ollama = LocalOllamaProvider.from_runtime_config(context.config, env)
    if local_ollama is not None:
        validation_error = await local_ollama.validate()
        if validation_error is not None:
            return _result(
                1,
                "",
                validation_error,
                error_message=validation_error,
                model=string(context.config.get("model")),
            )
    home = await prepare_managed_home(
        runtime_type="opencode_local",
        context=context,
        env=env,
    )
    ensure_octopus_cli_shim(env, home)
    runtime_provider = _runtime_provider_config(context.config)
    if runtime_provider is None and local_ollama is not None:
        runtime_provider = local_ollama.execution_provider()
    _materialize_runtime_provider_config(home, runtime_provider)
    apply_runtime_context_env(env, context)
    loaded_skills = materialize_runtime_skills(
        runtime_type="opencode_local",
        config=context.config,
        desired_skills=desired_skills_from_config(context.config),
        skills_home=home / ".claude" / "skills",
        location_label="managed Claude-compatible skills home",
    )
    timeout = context.config.get("timeoutSec", 0)
    timeout_sec = float(timeout) if isinstance(timeout, (float, int)) else 0.0
    result = await _run_once(
        command=command,
        args=args,
        cwd=cwd,
        prompt=prompt,
        env=env,
        context=context,
        timeout_sec=timeout_sec,
        loaded_skills=loaded_skills,
    )
    if (
        session_id
        and not result.timed_out
        and (result.exit_code or 0) != 0
        and result.result_json is not None
        and unknown_session(
            str(result.result_json.get("stdout") or ""),
            str(result.result_json.get("stderr") or ""),
            str(result.result_json.get("error") or ""),
        )
    ):
        await context.on_log(
            "stdout",
            (
                f'[octopus] OpenCode resume session "{session_id}" is unavailable; '
                "retrying with a fresh session.\n"
            ),
        )
        retry_config = dict(runtime_config)
        retry_config["sessionIdBefore"] = None
        runtime_context = retry_config.get("_octopus")
        if isinstance(runtime_context, dict):
            retry_config["_octopus"] = {**runtime_context, "sessionIdBefore": None}
        result = await _run_once(
            command=command,
            args=build_args(retry_config),
            cwd=cwd,
            prompt=prompt,
            env=env,
            context=context,
            timeout_sec=timeout_sec,
            loaded_skills=loaded_skills,
        )
    return result


async def _run_once(
    *,
    command: str,
    args: list[str],
    cwd: str | None,
    prompt: str,
    env: dict[str, str],
    context: RuntimeExecutionContext,
    timeout_sec: float,
    loaded_skills: list[dict[str, str | None]],
) -> RuntimeExecutionResult:
    line_buffer = bytearray()

    async def on_stdout_chunk(chunk: bytes) -> None:
        await context.on_log("stdout", chunk.decode(errors="replace"))
        line_buffer.extend(chunk)
        while True:
            newline = line_buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(line_buffer[: newline + 1])
            del line_buffer[: newline + 1]
            await _emit_opencode_stream_event(context, line.decode(errors="replace"))

    async def on_stderr_chunk(chunk: bytes) -> None:
        await context.on_log("stderr", chunk.decode(errors="replace"))

    process_result = await local_process_supervisor.run(
        command,
        *args,
        cwd=cwd,
        env=env,
        input_data=prompt.encode(),
        timeout_sec=timeout_sec,
        cancel_event=context.cancel_event,
        on_process_started=context.on_process_started,
        on_process_exited=context.on_process_exited,
        on_stdout_chunk=on_stdout_chunk,
        on_stderr_chunk=on_stderr_chunk,
    )
    if line_buffer:
        await _emit_opencode_stream_event(
            context, bytes(line_buffer).decode(errors="replace")
        )
    stdout_text = process_result.stdout.decode(errors="replace")
    stderr_text = process_result.stderr.decode(errors="replace")
    if process_result.cancelled:
        return _result(
            process_result.exit_code,
            stdout_text,
            stderr_text,
            signal=process_result.signal,
            error_message="Run cancelled",
            model=string(context.config.get("model")),
            loaded_skills=loaded_skills,
        )
    if process_result.timed_out:
        return _result(
            process_result.exit_code,
            stdout_text,
            stderr_text,
            timed_out=True,
            error_message=f"Timed out after {timeout_sec:g}s",
            model=string(context.config.get("model")),
            loaded_skills=loaded_skills,
        )
    parsed = parse_jsonl(stdout_text)
    error = parsed["errorMessage"]
    exit_code = process_result.exit_code
    final_error = error
    if error and (exit_code or 0) == 0 and not parsed["summary"]:
        exit_code = 1
    elif error and (exit_code or 0) == 0 and parsed["summary"]:
        final_error = None
    if (exit_code or 0) != 0 and not error:
        error = first_line(stderr_text) or f"OpenCode exited with code {exit_code}"
        final_error = error
    model = string(context.config.get("model"))
    return RuntimeExecutionResult(
        exit_code=exit_code,
        error_message=final_error,
        usage_json=parsed["usage"],
        session_id_after=parsed["sessionId"],
        result_json=_result_json(
            stdout_text, stderr_text, parsed, model, error, loaded_skills
        ),
        work_products=_work_products_from_opencode_writes(context, parsed),
    )


def _result(
    exit_code: int | None,
    stdout_text: str,
    stderr_text: str,
    *,
    signal: str | None = None,
    timed_out: bool = False,
    error_message: str | None = None,
    model: str | None = None,
    loaded_skills: list[dict[str, str | None]] | None = None,
) -> RuntimeExecutionResult:
    parsed = parse_jsonl(stdout_text)
    return RuntimeExecutionResult(
        exit_code=exit_code,
        signal=signal,
        timed_out=timed_out,
        error_message=error_message,
        usage_json=parsed["usage"],
        session_id_after=parsed["sessionId"],
        result_json=_result_json(
            stdout_text, stderr_text, parsed, model, error_message, loaded_skills or []
        ),
    )


async def _read_stdout(
    process: asyncio.subprocess.Process, context: RuntimeExecutionContext
) -> str:
    if process.stdout is None:
        return ""
    chunks: list[bytes] = []
    line_buffer = bytearray()
    while True:
        chunk = await process.stdout.read(65_536)
        if not chunk:
            break
        chunks.append(chunk)
        await context.on_log("stdout", chunk.decode(errors="replace"))
        line_buffer.extend(chunk)
        while True:
            newline = line_buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(line_buffer[: newline + 1])
            del line_buffer[: newline + 1]
            await _emit_opencode_stream_event(context, line.decode(errors="replace"))
    if line_buffer:
        await _emit_opencode_stream_event(
            context, bytes(line_buffer).decode(errors="replace")
        )
    return b"".join(chunks).decode(errors="replace")


async def _read_stderr(
    process: asyncio.subprocess.Process, context: RuntimeExecutionContext
) -> str:
    if process.stderr is None:
        return ""
    chunks: list[bytes] = []
    while True:
        chunk = await process.stderr.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
        await context.on_log("stderr", chunk.decode(errors="replace"))
    return b"".join(chunks).decode(errors="replace")


async def _emit_opencode_stream_event(
    context: RuntimeExecutionContext, raw_line: str
) -> None:
    if context.on_stream_event is None:
        return
    try:
        event = json.loads(raw_line.strip())
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict) or event.get("type") != "text":
        return
    part = event.get("part")
    if not isinstance(part, dict):
        return
    text = part.get("text")
    if isinstance(text, str) and text:
        await context.on_stream_event({"type": "assistant_delta", "delta": text})


def _materialize_runtime_provider_config(
    home: os.PathLike[str] | str, provider: dict | None
) -> None:
    if not isinstance(provider, dict):
        return
    provider_id = string(provider.get("providerId"))
    if provider_id is None:
        return
    model = provider.get("model")
    if not isinstance(model, dict):
        return
    model_id = string(model.get("modelId"))
    if model_id is None:
        return

    config_path = Path(home) / ".config" / "opencode" / "opencode.json"
    document = _read_opencode_config(config_path)
    providers = document.get("provider")
    if not isinstance(providers, dict):
        providers = {}
        document["provider"] = providers

    provider_entry: dict[str, object] = {
        "name": string(provider.get("name")) or provider_id,
    }
    npm_package = string(provider.get("npmPackage"))
    if npm_package is not None:
        provider_entry["npm"] = npm_package
    options: dict[str, object] = {}
    base_url = string(provider.get("baseUrl"))
    if base_url is not None:
        options["baseURL"] = base_url
    api_key = string(provider.get("apiKey"))
    if api_key is not None:
        options["apiKey"] = api_key
    provider_config = provider.get("config")
    if isinstance(provider_config, dict):
        extra_options = provider_config.get("options")
        if isinstance(extra_options, dict):
            options.update(
                {
                    key: value
                    for key, value in extra_options.items()
                    if isinstance(key, str)
                }
            )
    if options:
        provider_entry["options"] = options

    model_name = string(model.get("displayName")) or model_id
    provider_entry["models"] = {model_id: {"name": model_name}}
    providers[provider_id] = provider_entry

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _runtime_provider_config(config: dict) -> dict | None:
    runtime_context = config.get("_octopus")
    if not isinstance(runtime_context, dict):
        return None
    provider = runtime_context.get("runtimeProvider")
    return provider if isinstance(provider, dict) else None


def _read_opencode_config(config_path: Path) -> dict:
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _work_products_from_opencode_writes(
    context: RuntimeExecutionContext, parsed: dict
) -> list[dict[str, object]]:
    workspace_root = _workspace_root(context)
    if workspace_root is None:
        return []
    written_files = parsed.get("writtenFiles")
    if not isinstance(written_files, list):
        return []
    declared_paths = _normalized_path_set(parsed.get("declaredWorkProducts"))
    primary_paths = _normalized_path_set(parsed.get("primaryWorkProducts"))
    candidates: list[tuple[str, Path, bytes]] = []
    seen: set[str] = set()
    for value in written_files:
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            path = Path(value).expanduser().resolve()
        except OSError:
            continue
        if not _is_relative_to(path, workspace_root) or not path.is_file():
            continue
        rel_path = path.relative_to(workspace_root).as_posix()
        if rel_path in seen or _is_excluded_work_product_path(rel_path):
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if not content:
            continue
        seen.add(rel_path)
        candidates.append((rel_path, path, content))
    if not candidates:
        return []

    primary_path = next(
        (rel for rel, _, _ in candidates if rel in primary_paths),
        None,
    )
    if primary_path is None:
        primary_path = next(
            (rel for rel, _, _ in candidates if rel in declared_paths),
            candidates[0][0] if len(candidates) == 1 else None,
        )

    workspace_ref = _workspace_ref(context)
    products: list[dict[str, object]] = []
    for rel_path, path, content in candidates:
        products.append(
            {
                "title": rel_path,
                "type": "document"
                if path.suffix.lower() in {".md", ".txt"}
                else "artifact",
                "provider": "octopus",
                "externalId": f"opencode_write:{workspace_ref}:{rel_path}",
                "status": "active",
                "reviewState": "none",
                "isPrimary": rel_path == primary_path,
                "summary": "File written by OpenCode during this run.",
                "content": content,
                "contentType": mimetypes.guess_type(path.name)[0] or "text/plain",
                "filename": path.name,
                "metadata": {
                    "source": "opencode_write_event",
                    "workspacePath": rel_path,
                    "byteSize": len(content),
                },
            }
        )
    return products


def _workspace_root(context: RuntimeExecutionContext) -> Path | None:
    workspace_context = context.workspace
    workspace = None
    if isinstance(workspace_context, dict):
        candidate = workspace_context.get("octopusWorkspace")
        workspace = candidate if isinstance(candidate, dict) else workspace_context
    cwd = workspace.get("cwd") if isinstance(workspace, dict) else None
    if not isinstance(cwd, str) or not cwd.strip():
        cwd = context.config.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return None
    try:
        root = Path(cwd).expanduser().resolve()
    except OSError:
        return None
    return root if root.is_dir() else None


def _workspace_ref(context: RuntimeExecutionContext) -> str:
    workspace_context = context.workspace
    if isinstance(workspace_context, dict):
        workspace = workspace_context.get("octopusWorkspace")
        if isinstance(workspace, dict):
            workspace_id = string(workspace.get("id"))
            if workspace_id:
                return workspace_id
    return context.run_id


def _normalized_path_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        item.replace("\\", "/").strip()
        for item in value
        if isinstance(item, str) and item.strip()
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _is_excluded_work_product_path(rel_path: str) -> bool:
    parts = set(Path(rel_path).parts)
    return bool(
        parts
        & {
            ".git",
            ".mypy_cache",
            ".octopus",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "build",
            "dist",
            "node_modules",
        }
    )


def _result_json(
    stdout_text: str,
    stderr_text: str,
    parsed: dict,
    model: str | None,
    error: str | None,
    loaded_skills: list[dict[str, str | None]],
) -> dict:
    return {
        "stdout": stdout_text,
        "stderr": stderr_text,
        "summary": parsed["summary"],
        "costUsd": parsed["costUsd"],
        "provider": provider(model),
        "model": model,
        "loadedSkills": loaded_skills,
        "toolErrors": parsed.get("toolErrors", []),
        "modelUnavailable": model_unavailable(stdout_text, stderr_text, error),
        "authRequired": auth_required(stdout_text, stderr_text, error),
        "artifactEvidence": {
            "source": "opencode_write_event",
            "writtenPaths": parsed.get("writtenFiles", []),
            "declaredPaths": parsed.get("declaredWorkProducts", []),
            "primaryPaths": parsed.get("primaryWorkProducts", []),
        },
    }
