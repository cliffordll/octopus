from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from typing import Any

from ..common import runtime_subprocess_kwargs
from ..context_env import apply_runtime_context_env
from ..environment import clear_inherited_blocking_proxy_env, resolve_runtime_executable
from ..instructions import runtime_prompt_from_config
from ..local_skills import (
    desired_skills_from_config,
    ensure_control_plane_cli_shim,
    materialize_runtime_skills,
    prepare_managed_home,
)
from ..provider_config import apply_provider_env, provider_model_id, runtime_provider
from ..tool_capabilities import (
    append_runtime_tool_guidance,
    append_runtime_workspace_guidance,
)
from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .skills import _normalize_openclaw_agent_id, _openclaw_workspace_path

_DEFAULT_CONTEXT_WINDOW = 128000
# OpenClaw resolves --model against its own catalog; for an injected platform
# provider we register it as an openai-compatible custom provider/model.
_DEFAULT_API_ADAPTER = "openai-completions"


async def execute(context: RuntimeExecutionContext) -> RuntimeExecutionResult:
    config = context.config
    command = resolve_runtime_executable(_string(config.get("command")) or "openclaw")
    cwd = config.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("OpenClaw adapter cwd must be a string")
    prompt = append_runtime_workspace_guidance(
        append_runtime_tool_guidance(
            runtime_prompt_from_config(config), "openclaw_local"
        ),
        context.workspace,
    )

    env = dict(os.environ)
    configured_env = config.get("env")
    explicit_env_keys: set[str] = set()
    if isinstance(configured_env, dict):
        explicit_env_keys = {key for key in configured_env if isinstance(key, str)}
        env.update(
            {
                key: value
                for key, value in configured_env.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        )
    if context.env:
        explicit_env_keys.update(context.env)
        env.update(context.env)
    # Platform model auth/routing — OpenClaw `--local` honours these env vars.
    apply_provider_env(
        env,
        config,
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
    )
    clear_inherited_blocking_proxy_env(env, explicit_keys=explicit_env_keys)

    managed_home = await prepare_managed_home(
        runtime_type="openclaw_local",
        context=context,
        env=env,
    )
    openclaw_agent_id = _normalize_openclaw_agent_id(context.agent_id)
    openclaw_workspace = _openclaw_workspace_path(managed_home, openclaw_agent_id)
    ensure_control_plane_cli_shim(env, managed_home)
    apply_runtime_context_env(env, context)
    loaded_skills = materialize_runtime_skills(
        runtime_type="openclaw_local",
        config=context.config,
        desired_skills=desired_skills_from_config(context.config),
        skills_home=openclaw_workspace / "skills",
        location_label="managed OpenClaw agent workspace skills",
    )

    timeout = config.get("timeoutSec", 0)
    timeout_sec = float(timeout) if isinstance(timeout, (float, int)) else 0.0

    # Register the injected platform model into OpenClaw's per-agent catalog so
    # `--model <provider>/<model>` resolves; OpenClaw rejects unknown model ids.
    model_ref, register_error = await _ensure_model_registered(
        context, command, cwd, env, timeout_sec
    )

    session_key = _session_key(context)
    args = _build_args(config, session_key, model_ref)
    return await _run_attempt(
        context=context,
        command=command,
        args=args,
        prompt=prompt,
        cwd=cwd,
        env=env,
        timeout_sec=timeout_sec,
        register_error=register_error,
        loaded_skills=loaded_skills,
    )


# --------------------------------------------------------------------------- #
# model registration (openclaw config patch)
# --------------------------------------------------------------------------- #
async def _ensure_model_registered(
    context: RuntimeExecutionContext,
    command: str,
    cwd: str | None,
    env: dict[str, str],
    timeout_sec: float,
) -> tuple[str, str | None]:
    """Return (model_ref_for_cli, error). Registers a custom provider when an
    injected runtime-provider is present; otherwise falls back to config.model."""
    config = context.config
    raw_model = _string(config.get("model")) or ""
    provider = runtime_provider(config)
    if provider is None:
        # No injected provider: trust whatever OpenClaw already has configured.
        return raw_model, None

    base_url = _string(provider.get("baseUrl"))
    api_key = _string(provider.get("apiKey"))
    model_id = provider_model_id(config) or raw_model.partition("/")[2] or raw_model
    if not (base_url and api_key and model_id):
        return raw_model, None

    provider_name = _openclaw_provider_name(raw_model.partition("/")[0] or model_id)
    model_meta = provider.get("model")
    display = model_id
    context_window = _DEFAULT_CONTEXT_WINDOW
    if isinstance(model_meta, dict):
        display = _string(model_meta.get("displayName")) or model_id
        metadata = model_meta.get("metadata")
        if isinstance(metadata, dict):
            cw = metadata.get("contextWindow") or metadata.get("contextTokens")
            if isinstance(cw, (int, float)) and cw > 0:
                context_window = int(cw)

    patch = {
        "models": {
            "providers": {
                provider_name: {
                    "baseUrl": base_url,
                    "apiKey": api_key,
                    "auth": "api-key",
                    "api": _DEFAULT_API_ADAPTER,
                    "contextWindow": context_window,
                    "models": [
                        {
                            "id": model_id,
                            "name": display,
                            "contextWindow": context_window,
                        }
                    ],
                }
            }
        }
    }
    rc, _out, err = await _run_cli(
        command,
        ["config", "patch", "--stdin"],
        cwd=cwd,
        env=env,
        input_text=json.dumps(patch),
        timeout_sec=timeout_sec if timeout_sec > 0 else 60.0,
    )
    model_ref = f"{provider_name}/{model_id}"
    if rc != 0:
        message = _first_meaningful_line(err) or f"config patch exited with {rc}"
        await context.on_log(
            "stderr",
            f"[octopus] OpenClaw model registration failed: {message}\n",
        )
        return model_ref, f"OpenClaw model registration failed: {message}"
    return model_ref, None


def _openclaw_provider_name(raw: str) -> str:
    # OpenClaw provider id must match ^[a-z][a-z0-9_-]{0,63}$
    slug = re.sub(r"[^a-z0-9_-]", "-", (raw or "").lower()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"epai-{slug}".strip("-")
    return slug[:64] or "epai"


# --------------------------------------------------------------------------- #
# agent run
# --------------------------------------------------------------------------- #
def _build_args(config: dict[str, Any], session_key: str, model_ref: str) -> list[str]:
    # 不传 --agent：openclaw 的 --agent 要求该 agent 预先在 openclaw 注册（且注册是交互式的），
    # 否则报 "Unknown agent id" 直接令 run 失败。改用 --session-key（agent:<id>:<run>），
    # openclaw 据此自动推断/创建 per-agent workspace（workspace-<id>），与 skills 落点一致。
    args = [
        "agent",
        "--local",
        "--json",
        "--session-key",
        session_key,
    ]
    if model_ref:
        args.extend(["--model", model_ref])
    thinking = _string(config.get("thinking") or config.get("effort"))
    if thinking:
        args.extend(["--thinking", thinking])
    extra_args = config.get("extraArgs", config.get("args", []))
    if isinstance(extra_args, list) and all(isinstance(a, str) for a in extra_args):
        args.extend(extra_args)
    return args


def _session_key(context: RuntimeExecutionContext) -> str:
    agent = re.sub(r"[^A-Za-z0-9_.-]", "-", context.agent_id or "main") or "main"
    run = re.sub(r"[^A-Za-z0-9_.-]", "-", context.run_id or "run") or "run"
    return f"agent:{agent}:{run}"


async def _run_attempt(
    *,
    context: RuntimeExecutionContext,
    command: str,
    args: list[str],
    prompt: str,
    cwd: str | None,
    env: dict[str, str],
    timeout_sec: float,
    register_error: str | None,
    loaded_skills: list[dict[str, str | None]],
) -> RuntimeExecutionResult:
    full_args = [*args, "-m", prompt]
    rc, stdout, stderr, timed_out, signal = await _run_with_lifecycle(
        context=context,
        command=command,
        args=full_args,
        cwd=cwd,
        env=env,
        timeout_sec=timeout_sec,
    )
    if stdout:
        await context.on_log("stdout", stdout)
    cleaned_stderr = _strip_benign_stderr(stderr)
    if cleaned_stderr:
        await context.on_log("stderr", cleaned_stderr)

    if timed_out:
        return RuntimeExecutionResult(
            exit_code=rc,
            signal=signal,
            timed_out=True,
            error_message=f"Timed out after {timeout_sec:g}s",
            result_json=_result_json(
                stdout, cleaned_stderr, "", register_error, loaded_skills
            ),
        )

    text, usage, session_id, _data = _parse_output(stdout)
    error = register_error
    if rc != 0:
        error = (
            _first_meaningful_line(cleaned_stderr)
            or register_error
            or f"OpenClaw exited with code {rc}"
        )
    return RuntimeExecutionResult(
        exit_code=rc,
        signal=signal,
        error_message=error,
        usage_json=usage or None,
        session_id_after=session_id,
        result_json=_result_json(
            stdout, cleaned_stderr, text, register_error, loaded_skills
        ),
    )


def _result_json(
    stdout: str,
    stderr: str,
    summary: str,
    register_error: str | None,
    loaded_skills: list[dict[str, str | None]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "summary": summary,
        "loadedSkills": loaded_skills,
    }
    if register_error:
        payload["modelRegistrationError"] = register_error
    return payload


# --------------------------------------------------------------------------- #
# output parsing (defensive: OpenClaw --json shape may vary by version)
# --------------------------------------------------------------------------- #
_TEXT_KEYS = (
    "text",
    "reply",
    "result",
    "message",
    "content",
    "response",
    "output",
    "summary",
    "assistant",
)


def _parse_output(stdout: str) -> tuple[str, dict[str, Any], str | None, Any]:
    """Parse `openclaw agent --json` output.

    Real shape (OpenClaw 2026.6):
      {"payloads":[{"text":"...","mediaUrl":null}],
       "meta":{"agentMeta":{"sessionId":"...","usage":{"input":..,"output":..,"total":..}}}}
    Falls back to top-level text keys for other/older shapes.
    """
    data = _load_json_loose(stdout)
    text = ""
    usage: dict[str, Any] = {}
    session_id: str | None = None
    if isinstance(data, dict):
        payloads = data.get("payloads")
        if isinstance(payloads, list):
            parts = [
                p["text"].strip()
                for p in payloads
                if isinstance(p, dict)
                and isinstance(p.get("text"), str)
                and p["text"].strip()
            ]
            text = "\n\n".join(parts)
        meta = data.get("meta")
        agent_meta = meta.get("agentMeta") if isinstance(meta, dict) else None
        if isinstance(agent_meta, dict):
            session_id = _string(agent_meta.get("sessionId"))
            raw_usage = agent_meta.get("usage")
            if isinstance(raw_usage, dict):
                usage = {
                    "inputTokens": _int(raw_usage.get("input")),
                    "outputTokens": _int(raw_usage.get("output")),
                    "totalTokens": _int(raw_usage.get("total")),
                }
        if not text:
            for key in _TEXT_KEYS:
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
    return text, usage, session_id, data


def _load_json_loose(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") or candidate.startswith("["):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return None


_BENIGN_STDERR_PREFIXES = ("[diagnostic]", "[model-fallback", "[agent/embedded]")


def _strip_benign_stderr(value: str) -> str:
    if not value:
        return value
    kept = [line for line in value.splitlines(keepends=True) if not _is_benign(line)]
    return "".join(kept)


def _is_benign(line: str) -> bool:
    text = line.strip()
    return bool(text) and any(text.startswith(p) for p in _BENIGN_STDERR_PREFIXES)


def _first_meaningful_line(value: str) -> str | None:
    for line in reversed(value.splitlines()):
        text = line.strip()
        if text and not any(text.startswith(p) for p in _BENIGN_STDERR_PREFIXES):
            return text
    return next((line.strip() for line in value.splitlines() if line.strip()), None)


# --------------------------------------------------------------------------- #
# subprocess helpers
# --------------------------------------------------------------------------- #
async def _run_cli(
    command: str,
    args: list[str],
    *,
    cwd: str | None,
    env: dict[str, str],
    input_text: str | None,
    timeout_sec: float,
) -> tuple[int | None, str, str]:
    """Simple blocking-capable CLI run (used for config patch)."""
    try:
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE if input_text is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **runtime_subprocess_kwargs(),
        )
    except (PermissionError, OSError):
        return await asyncio.to_thread(
            _run_blocking, command, args, cwd, env, input_text, timeout_sec
        )
    payload = input_text.encode() if input_text is not None else None
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(payload),
            timeout=timeout_sec if timeout_sec > 0 else None,
        )
    except TimeoutError:
        process.kill()
        await process.communicate()
        return None, "", "timed out"
    return (
        process.returncode,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


def _run_blocking(
    command: str,
    args: list[str],
    cwd: str | None,
    env: dict[str, str],
    input_text: str | None,
    timeout_sec: float,
) -> tuple[int | None, str, str]:
    try:
        completed = subprocess.run(
            [command, *args],
            cwd=cwd,
            env=env,
            input=input_text.encode() if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec if timeout_sec > 0 else None,
            **runtime_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return None, "", "timed out"
    except OSError as exc:
        return 1, "", str(exc)
    return (
        completed.returncode,
        (completed.stdout or b"").decode(errors="replace"),
        (completed.stderr or b"").decode(errors="replace"),
    )


async def _run_with_lifecycle(
    *,
    context: RuntimeExecutionContext,
    command: str,
    args: list[str],
    cwd: str | None,
    env: dict[str, str],
    timeout_sec: float,
) -> tuple[int | None, str, str, bool, str | None]:
    try:
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **runtime_subprocess_kwargs(),
        )
    except (PermissionError, OSError) as exc:
        rc, out, err = await asyncio.to_thread(
            _run_blocking, command, args, cwd, env, None, timeout_sec
        )
        if not err:
            err = str(exc)
        return rc, out, err, False, None

    pid = getattr(process, "pid", None)
    if context.on_process_started is not None and isinstance(pid, int):
        await context.on_process_started(pid, datetime.now(UTC))

    communication = asyncio.create_task(process.communicate())
    cancelled = (
        asyncio.create_task(context.cancel_event.wait())
        if context.cancel_event is not None
        else None
    )
    try:
        waiters: set[asyncio.Task[Any]] = {communication}
        if cancelled is not None:
            waiters.add(cancelled)
        done, _pending = await asyncio.wait(
            waiters,
            timeout=timeout_sec if timeout_sec > 0 else None,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancelled is not None and cancelled in done:
            process.kill()
            stdout, stderr = await communication
            await process.wait()
            return (
                process.returncode,
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
                False,
                "SIGTERM",
            )
        if communication not in done:
            # timeout
            communication.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await communication
            process.kill()
            stdout, stderr = await process.communicate()
            await process.wait()
            return (
                process.returncode,
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
                True,
                None,
            )
        stdout, stderr = communication.result()
        return (
            process.returncode,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
            False,
            None,
        )
    finally:
        if cancelled is not None and not cancelled.done():
            cancelled.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancelled


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
