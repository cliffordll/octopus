from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime

from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .protocol import (
    build_args,
    describe_failure,
    first_line,
    login_required,
    max_turns,
    parse_stream_json,
    string,
)


async def execute(context: RuntimeExecutionContext) -> RuntimeExecutionResult:
    command = string(context.config.get("command")) or "claude"
    cwd = context.config.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("Claude adapter cwd must be a string")
    prompt = string(context.config.get("promptTemplate")) or ""
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
            stdout, stderr = await asyncio.wait_for(communication, timeout=timeout_sec)
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
    parsed = parse_stream_json(stdout_text)
    error = None
    if process.returncode != 0:
        if login_required(stdout_text, stderr_text, parsed["resultJson"]):
            error = "Claude CLI login required"
        else:
            error = describe_failure(parsed["resultJson"]) or first_line(stderr_text)
        error = error or f"Claude exited with code {process.returncode}"
    return RuntimeExecutionResult(
        exit_code=process.returncode,
        error_message=error,
        usage_json=parsed["usage"],
        session_id_after=parsed["sessionId"],
        result_json=_result_json(stdout_text, stderr_text, parsed),
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
    parsed = parse_stream_json(stdout_text)
    return RuntimeExecutionResult(
        exit_code=exit_code,
        signal=signal,
        timed_out=timed_out,
        error_message=error_message,
        usage_json=parsed["usage"],
        session_id_after=parsed["sessionId"],
        result_json=_result_json(stdout_text, stderr_text, parsed),
    )


def _result_json(stdout_text: str, stderr_text: str, parsed: dict) -> dict:
    return {
        "stdout": stdout_text,
        "stderr": stderr_text,
        "summary": parsed["summary"],
        "model": parsed["model"],
        "costUsd": parsed["costUsd"],
        "loginRequired": login_required(stdout_text, stderr_text, parsed["resultJson"]),
        "maxTurnsReached": max_turns(parsed["resultJson"]),
        "result": parsed["resultJson"],
    }
