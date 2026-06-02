from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from ..context_env import apply_runtime_context_env
from ..environment import resolve_runtime_executable
from ..instructions import runtime_prompt_from_config
from ..local_skills import (
    desired_skills_from_config,
    materialize_runtime_skills,
    prepare_managed_home,
)
from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .protocol import (
    auth_required,
    build_args,
    first_line,
    model_unavailable,
    parse_jsonl,
    provider,
    string,
)


async def execute(context: RuntimeExecutionContext) -> RuntimeExecutionResult:
    command = resolve_runtime_executable(
        string(context.config.get("command")) or "opencode"
    )
    cwd = context.config.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("OpenCode adapter cwd must be a string")
    prompt = runtime_prompt_from_config(context.config)
    args = build_args(context.config)
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
    home = await prepare_managed_home(
        runtime_type="opencode_local",
        context=context,
        env=env,
    )
    _materialize_runtime_provider_config(home, context.config)
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
    process = await asyncio.create_subprocess_exec(
        command,
        *args,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    pid = getattr(process, "pid", None)
    if context.on_process_started is not None and isinstance(pid, int):
        await context.on_process_started(pid, datetime.now(UTC))
    if not _supports_streaming_process(process):
        return await _execute_with_communicate(
            process=process,
            context=context,
            prompt=prompt,
            timeout_sec=timeout_sec,
            loaded_skills=loaded_skills,
        )
    stdout_task = asyncio.create_task(_read_stdout(process, context))
    stderr_task = asyncio.create_task(_read_stderr(process))
    stdin_task = asyncio.create_task(_write_stdin(process, prompt))
    wait_task = asyncio.create_task(process.wait())
    try:
        cancelled = (
            asyncio.create_task(context.cancel_event.wait())
            if context.cancel_event is not None
            else None
        )
        if cancelled is not None:
            done, _ = await asyncio.wait(
                {wait_task, cancelled},
                timeout=timeout_sec if timeout_sec > 0 else None,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancelled in done:
                process.kill()
                await process.wait()
                await stdin_task
                stdout_text = await stdout_task
                stderr_text = await stderr_task
                return _result(
                    process.returncode,
                    stdout_text,
                    stderr_text,
                    signal="SIGTERM",
                    error_message="Run cancelled",
                    model=string(context.config.get("model")),
                    loaded_skills=loaded_skills,
                )
            cancelled.cancel()
            if wait_task not in done:
                raise TimeoutError
        elif timeout_sec > 0:
            await asyncio.wait_for(wait_task, timeout=timeout_sec)
        else:
            await wait_task
    except TimeoutError:
        process.kill()
        await process.wait()
        await stdin_task
        stdout_text = await stdout_task
        stderr_text = await stderr_task
        return _result(
            process.returncode,
            stdout_text,
            stderr_text,
            timed_out=True,
            error_message=f"Timed out after {timeout_sec:g}s",
            model=string(context.config.get("model")),
            loaded_skills=loaded_skills,
        )
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        for task in (stdin_task, stdout_task, stderr_task, wait_task):
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(stdin_task, stdout_task, stderr_task, wait_task)
        raise
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            await stdin_task

    stdout_text = await stdout_task
    stderr_text = await stderr_task
    if stdout_text:
        await context.on_log("stdout", stdout_text)
    if stderr_text:
        await context.on_log("stderr", stderr_text)
    parsed = parse_jsonl(stdout_text)
    error = parsed["errorMessage"]
    exit_code = process.returncode
    if error and (exit_code or 0) == 0:
        exit_code = 1
    if (exit_code or 0) != 0 and not error:
        error = first_line(stderr_text) or f"OpenCode exited with code {exit_code}"
    model = string(context.config.get("model"))
    return RuntimeExecutionResult(
        exit_code=exit_code,
        error_message=error,
        usage_json=parsed["usage"],
        session_id_after=parsed["sessionId"],
        result_json=_result_json(
            stdout_text, stderr_text, parsed, model, error, loaded_skills
        ),
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


async def _write_stdin(process: asyncio.subprocess.Process, prompt: str) -> None:
    if process.stdin is None:
        return
    process.stdin.write(prompt.encode())
    await process.stdin.drain()
    process.stdin.close()


async def _execute_with_communicate(
    *,
    process: asyncio.subprocess.Process,
    context: RuntimeExecutionContext,
    prompt: str,
    timeout_sec: float,
    loaded_skills: list[dict[str, str | None]],
) -> RuntimeExecutionResult:
    communication = asyncio.create_task(process.communicate(prompt.encode()))
    try:
        if timeout_sec > 0:
            stdout, stderr = await asyncio.wait_for(communication, timeout=timeout_sec)
        else:
            stdout, stderr = await communication
    except TimeoutError:
        communication.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await communication
        process.kill()
        stdout, stderr = await process.communicate()
        return _result(
            getattr(process, "returncode", None),
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
            timed_out=True,
            error_message=f"Timed out after {timeout_sec:g}s",
            model=string(context.config.get("model")),
            loaded_skills=loaded_skills,
        )
    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
    await _emit_opencode_stream_events_from_text(context, stdout_text)
    if stdout_text:
        await context.on_log("stdout", stdout_text)
    if stderr_text:
        await context.on_log("stderr", stderr_text)
    parsed = parse_jsonl(stdout_text)
    error = parsed["errorMessage"]
    exit_code = getattr(process, "returncode", None)
    if error and (exit_code or 0) == 0:
        exit_code = 1
    if (exit_code or 0) != 0 and not error:
        error = first_line(stderr_text) or f"OpenCode exited with code {exit_code}"
    model = string(context.config.get("model"))
    return RuntimeExecutionResult(
        exit_code=exit_code,
        error_message=error,
        usage_json=parsed["usage"],
        session_id_after=parsed["sessionId"],
        result_json=_result_json(
            stdout_text, stderr_text, parsed, model, error, loaded_skills
        ),
    )


async def _read_stdout(
    process: asyncio.subprocess.Process, context: RuntimeExecutionContext
) -> str:
    if process.stdout is None:
        return ""
    chunks: list[str] = []
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        text = line.decode(errors="replace")
        chunks.append(text)
        await _emit_opencode_stream_event(context, text)
    return "".join(chunks)


async def _read_stderr(process: asyncio.subprocess.Process) -> str:
    if process.stderr is None:
        return ""
    chunks: list[bytes] = []
    while True:
        chunk = await process.stderr.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
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


async def _emit_opencode_stream_events_from_text(
    context: RuntimeExecutionContext, stdout_text: str
) -> None:
    if context.on_stream_event is None:
        return
    for raw_line in stdout_text.splitlines():
        await _emit_opencode_stream_event(context, raw_line)


def _supports_streaming_process(process: object) -> bool:
    return (
        getattr(process, "stdin", None) is not None
        and getattr(process, "stdout", None) is not None
        and getattr(process, "stderr", None) is not None
        and callable(getattr(process, "wait", None))
    )


def _materialize_runtime_provider_config(
    home: os.PathLike[str] | str, config: dict
) -> None:
    runtime_context = config.get("_octopus")
    if not isinstance(runtime_context, dict):
        return
    provider = runtime_context.get("runtimeProvider")
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


def _read_opencode_config(config_path: Path) -> dict:
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


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
        "modelUnavailable": model_unavailable(stdout_text, stderr_text, error),
        "authRequired": auth_required(stdout_text, stderr_text, error),
    }
