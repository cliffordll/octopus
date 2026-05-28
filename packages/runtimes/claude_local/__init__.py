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


class ClaudeLocalRuntimeAdapter(RuntimeCapabilityMixin):
    type = "claude_local"
    supports_local_agent_jwt = True
    agent_configuration_doc = (
        "Configure cwd, model, effort, maxTurnsPerRun, env and Claude CLI options."
    )
    quota_provider = "anthropic"
    _models = [{"id": "claude-sonnet-4.5", "label": "Claude Sonnet 4.5"}]

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        command = _string(context.config.get("command")) or "claude"
        cwd = context.config.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError("Claude adapter cwd must be a string")
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
        parsed = _parse_stream_json(stdout_text)
        error = None
        if process.returncode != 0:
            login = _login_required(stdout_text, stderr_text, parsed["resultJson"])
            if login:
                error = "Claude CLI login required"
            else:
                error = _describe_failure(parsed["resultJson"]) or _first_line(
                    stderr_text
                )
            error = error or f"Claude exited with code {process.returncode}"
        return RuntimeExecutionResult(
            exit_code=process.returncode,
            error_message=error,
            usage_json=parsed["usage"],
            session_id_after=parsed["sessionId"],
            result_json={
                "stdout": stdout_text,
                "stderr": stderr_text,
                "summary": parsed["summary"],
                "model": parsed["model"],
                "costUsd": parsed["costUsd"],
                "loginRequired": _login_required(
                    stdout_text, stderr_text, parsed["resultJson"]
                ),
                "maxTurnsReached": _max_turns(parsed["resultJson"]),
                "result": parsed["resultJson"],
            },
        )

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        command = _string(config.get("command")) or "claude"
        return RuntimeEnvironmentTestResult(
            agent_runtime_type=self.type,
            status="ok",
            checks=[
                {
                    "id": "command",
                    "label": "Claude CLI command",
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
    args.extend(["--print", "-", "--output-format", "stream-json", "--verbose"])
    model = _string(config.get("model"))
    if model:
        args.extend(["--model", model])
    effort = _string(config.get("effort") or config.get("modelReasoningEffort"))
    if effort:
        args.extend(["--effort", effort])
    max_turns = config.get("maxTurnsPerRun")
    if isinstance(max_turns, int) and not isinstance(max_turns, bool) and max_turns > 0:
        args.extend(["--max-turns", str(max_turns)])
    if config.get("dangerouslySkipPermissions") is True:
        args.extend(["--dangerously-skip-permissions"])
    if config.get("chrome") is True:
        args.append("--chrome")
    return args


def _parse_stream_json(stdout: str) -> dict[str, Any]:
    session_id: str | None = None
    model = ""
    final_result: dict[str, Any] | None = None
    assistant_texts: list[str] = []
    for raw_line in stdout.splitlines():
        try:
            event = json.loads(raw_line.strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "system" and event.get("subtype") == "init":
            session_id = _string(event.get("session_id")) or session_id
            model = _string(event.get("model")) or model
        elif event_type == "assistant":
            session_id = _string(event.get("session_id")) or session_id
            message = event.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    assistant_texts.extend(_assistant_texts(content))
        elif event_type == "result":
            final_result = event
            session_id = _string(event.get("session_id")) or session_id
    usage = None
    summary = "\n\n".join(assistant_texts).strip()
    cost_usd = None
    if final_result is not None:
        usage = _usage(final_result.get("usage"))
        summary = _string(final_result.get("result")) or summary
        raw_cost = final_result.get("total_cost_usd")
        if isinstance(raw_cost, (float, int)) and not isinstance(raw_cost, bool):
            cost_usd = float(raw_cost)
    return {
        "sessionId": session_id,
        "model": model,
        "usage": usage,
        "summary": summary,
        "costUsd": cost_usd,
        "resultJson": final_result,
    }


def _assistant_texts(content: list[Any]) -> list[str]:
    texts: list[str] = []
    for entry in content:
        if isinstance(entry, dict) and entry.get("type") == "text":
            text = _string(entry.get("text"))
            if text:
                texts.append(text)
    return texts


def _usage(value: Any) -> dict[str, int]:
    data = value if isinstance(value, dict) else {}
    return {
        "inputTokens": _integer(data.get("input_tokens")),
        "cachedInputTokens": _integer(data.get("cache_read_input_tokens"))
        + _integer(data.get("cache_creation_input_tokens")),
        "outputTokens": _integer(data.get("output_tokens")),
    }


def _login_required(
    stdout: str, stderr: str, result_json: dict[str, Any] | None
) -> bool:
    messages = [stdout, stderr]
    if result_json is not None:
        for key in ("result", "error", "message"):
            value = result_json.get(key)
            if isinstance(value, str):
                messages.append(value)
    text = "\n".join(messages).lower()
    return any(
        marker in text
        for marker in (
            "not logged in",
            "please log in",
            "claude login",
            "login required",
            "requires login",
            "unauthorized",
            "authentication required",
        )
    )


def _describe_failure(result_json: dict[str, Any] | None) -> str | None:
    if result_json is None:
        return None
    subtype = _string(result_json.get("subtype"))
    result = _string(result_json.get("result"))
    if subtype and result:
        return f"Claude run failed: subtype={subtype}: {result}"
    if subtype:
        return f"Claude run failed: subtype={subtype}"
    return result


def _max_turns(result_json: dict[str, Any] | None) -> bool:
    if result_json is None:
        return False
    subtype = (_string(result_json.get("subtype")) or "").lower()
    stop_reason = (_string(result_json.get("stop_reason")) or "").lower()
    result = _string(result_json.get("result")) or ""
    return (
        subtype == "error_max_turns"
        or stop_reason == "max_turns"
        or "max turns" in result.lower()
        or "maximum turns" in result.lower()
    )


def _result(
    exit_code: int | None,
    stdout: bytes,
    stderr: bytes,
    *,
    signal: str | None = None,
    timed_out: bool = False,
    error_message: str | None = None,
) -> RuntimeExecutionResult:
    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
    parsed = _parse_stream_json(stdout_text)
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
            "model": parsed["model"],
            "costUsd": parsed["costUsd"],
            "loginRequired": _login_required(
                stdout_text, stderr_text, parsed["resultJson"]
            ),
            "maxTurnsReached": _max_turns(parsed["resultJson"]),
            "result": parsed["resultJson"],
        },
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_line(value: str) -> str | None:
    return next((line.strip() for line in value.splitlines() if line.strip()), None)
