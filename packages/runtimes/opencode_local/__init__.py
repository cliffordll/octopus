from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from typing import Any

from ..common import RuntimeCapabilityMixin
from ..types import (
    RuntimeEnvironmentTestResult,
    RuntimeExecutionContext,
    RuntimeExecutionResult,
)


class OpenCodeLocalRuntimeAdapter(RuntimeCapabilityMixin):
    type = "opencode_local"
    supports_local_agent_jwt = True
    agent_configuration_doc = (
        "Configure cwd, model, variant, env and OpenCode CLI options."
    )
    _models = [{"id": "opencode/default", "label": "OpenCode Default"}]

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        command = _string(context.config.get("command")) or "opencode"
        cwd = context.config.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError("OpenCode adapter cwd must be a string")
        prompt = _string(context.config.get("promptTemplate")) or ""
        args = _build_args(context.config)
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
        communication = asyncio.create_task(process.communicate(prompt.encode()))
        try:
            cancelled = (
                asyncio.create_task(context.cancel_event.wait())
                if context.cancel_event is not None
                else None
            )
            if cancelled is not None:
                done, _ = await asyncio.wait(
                    {communication, cancelled},
                    timeout=timeout_sec if timeout_sec > 0 else None,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancelled in done:
                    process.kill()
                    stdout, stderr = await communication
                    await process.wait()
                    return _result(
                        process.returncode,
                        stdout,
                        stderr,
                        signal="SIGTERM",
                        error_message="Run cancelled",
                        model=_string(context.config.get("model")),
                    )
                cancelled.cancel()
                if communication not in done:
                    raise TimeoutError
                stdout, stderr = communication.result()
            elif timeout_sec > 0:
                stdout, stderr = await asyncio.wait_for(
                    communication, timeout=timeout_sec
                )
            else:
                stdout, stderr = await communication
        except TimeoutError:
            communication.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await communication
            process.kill()
            stdout, stderr = await process.communicate()
            await process.wait()
            return _result(
                process.returncode,
                stdout,
                stderr,
                timed_out=True,
                error_message=f"Timed out after {timeout_sec:g}s",
                model=_string(context.config.get("model")),
            )
        except asyncio.CancelledError:
            communication.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await communication
            process.kill()
            await process.communicate()
            await process.wait()
            raise

        stdout_text = stdout.decode(errors="replace")
        stderr_text = stderr.decode(errors="replace")
        if stdout_text:
            await context.on_log("stdout", stdout_text)
        if stderr_text:
            await context.on_log("stderr", stderr_text)
        parsed = _parse_jsonl(stdout_text)
        error = parsed["errorMessage"]
        exit_code = process.returncode
        if error and (exit_code or 0) == 0:
            exit_code = 1
        if (exit_code or 0) != 0 and not error:
            error = _first_line(stderr_text) or f"OpenCode exited with code {exit_code}"
        model = _string(context.config.get("model"))
        return RuntimeExecutionResult(
            exit_code=exit_code,
            error_message=error,
            usage_json=parsed["usage"],
            session_id_after=parsed["sessionId"],
            result_json={
                "stdout": stdout_text,
                "stderr": stderr_text,
                "summary": parsed["summary"],
                "costUsd": parsed["costUsd"],
                "provider": _provider(model),
                "model": model,
                "modelUnavailable": _model_unavailable(stdout_text, stderr_text, error),
                "authRequired": _auth_required(stdout_text, stderr_text, error),
            },
        )

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        command = _string(config.get("command")) or "opencode"
        return RuntimeEnvironmentTestResult(
            agent_runtime_type=self.type,
            status="ok",
            checks=[
                {
                    "id": "command",
                    "label": "OpenCode CLI command",
                    "status": "ok",
                    "message": f"Runtime command is configured: {command}",
                    "hint": None,
                }
            ],
        )

    async def list_models(self) -> list[dict[str, str]]:
        return self._models


def _build_args(config: dict[str, Any]) -> list[str]:
    args = _string_list(config.get("extraArgs", config.get("args", [])))
    args.extend(["run", "--format", "json"])
    model = _string(config.get("model"))
    if model:
        args.extend(["--model", model])
    variant = _string(config.get("variant"))
    if variant:
        args.extend(["--variant", variant])
    return args


def _parse_jsonl(stdout: str) -> dict[str, Any]:
    session_id: str | None = None
    messages: list[str] = []
    errors: list[str] = []
    usage = {"inputTokens": 0, "cachedInputTokens": 0, "outputTokens": 0}
    cost_usd = 0.0
    for raw_line in stdout.splitlines():
        try:
            event = json.loads(raw_line.strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        current_session_id = _string(event.get("sessionID"))
        if current_session_id:
            session_id = current_session_id
        event_type = event.get("type")
        if event_type == "text":
            part = event.get("part")
            if isinstance(part, dict):
                text = _string(part.get("text"))
                if text:
                    messages.append(text)
        elif event_type == "step_finish":
            part = event.get("part")
            if isinstance(part, dict):
                tokens = part.get("tokens")
                token_data = tokens if isinstance(tokens, dict) else {}
                cache = token_data.get("cache")
                cache_data = cache if isinstance(cache, dict) else {}
                usage["inputTokens"] += _integer(token_data.get("input"))
                usage["cachedInputTokens"] += _integer(cache_data.get("read"))
                usage["outputTokens"] += _integer(token_data.get("output")) + _integer(
                    token_data.get("reasoning")
                )
                cost_usd += _float(part.get("cost"))
        elif event_type == "tool_use":
            part = event.get("part")
            if isinstance(part, dict):
                state = part.get("state")
                if isinstance(state, dict) and state.get("status") == "error":
                    text = _string(state.get("error"))
                    if text:
                        errors.append(text)
        elif event_type == "error":
            text = _error_text(event.get("error") or event.get("message"))
            if text:
                errors.append(text)
    return {
        "sessionId": session_id,
        "summary": "\n\n".join(messages).strip(),
        "usage": usage,
        "costUsd": cost_usd,
        "errorMessage": "\n".join(errors) if errors else None,
    }


def _error_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("message", "error", "name", "code"):
            text = _string(value.get(key))
            if text:
                return text
        data = value.get("data")
        if isinstance(data, dict):
            return _string(data.get("message"))
    return None


def _provider(model: str | None) -> str | None:
    if not model or "/" not in model:
        return None
    return model.split("/", 1)[0].strip() or None


def _model_unavailable(stdout: str, stderr: str, error: str | None) -> bool:
    haystack = "\n".join([stdout, stderr, error or ""]).lower()
    return any(
        marker in haystack
        for marker in ("model unavailable", "unknown model", "model not found")
    )


def _auth_required(stdout: str, stderr: str, error: str | None) -> bool:
    haystack = "\n".join([stdout, stderr, error or ""]).lower()
    return any(
        marker in haystack
        for marker in (
            "auth required",
            "authentication required",
            "unauthorized",
            "api key",
        )
    )


def _result(
    exit_code: int | None,
    stdout: bytes,
    stderr: bytes,
    *,
    signal: str | None = None,
    timed_out: bool = False,
    error_message: str | None = None,
    model: str | None = None,
) -> RuntimeExecutionResult:
    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
    parsed = _parse_jsonl(stdout_text)
    return RuntimeExecutionResult(
        exit_code=exit_code,
        signal=signal,
        timed_out=timed_out,
        error_message=error_message,
        usage_json=parsed["usage"],
        session_id_after=parsed["sessionId"],
        result_json={
            "stdout": stdout_text,
            "stderr": stderr_text,
            "summary": parsed["summary"],
            "costUsd": parsed["costUsd"],
            "provider": _provider(model),
            "model": model,
            "modelUnavailable": _model_unavailable(
                stdout_text, stderr_text, error_message
            ),
            "authRequired": _auth_required(stdout_text, stderr_text, error_message),
        },
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _float(value: Any) -> float:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else 0.0
    )


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_line(value: str) -> str | None:
    return next((line.strip() for line in value.splitlines() if line.strip()), None)
