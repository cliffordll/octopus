from __future__ import annotations

import asyncio  # noqa: F401 -- retained for subprocess monkeypatch compatibility
import os

from ..environment import resolve_runtime_executable
from ..local_process import local_process_supervisor
from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .protocol import args, configured_env


async def execute(context: RuntimeExecutionContext) -> RuntimeExecutionResult:
    command = context.config.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("Process adapter missing command")
    command = resolve_runtime_executable(command)
    process_args = args(context.config.get("args"))
    cwd = context.config.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("Process adapter cwd must be a string")
    env = dict(os.environ)
    env.update(configured_env(context.config.get("env")))
    if context.env:
        env.update(context.env)
    timeout = context.config.get("timeoutSec", 0)
    timeout_sec = float(timeout) if isinstance(timeout, (float, int)) else 0.0
    process_result = await local_process_supervisor.run(
        command,
        *process_args,
        cwd=cwd,
        env=env,
        timeout_sec=timeout_sec,
        cancel_event=context.cancel_event,
        on_process_started=context.on_process_started,
        on_process_exited=context.on_process_exited,
    )
    if process_result.cancelled:
        return _result(
            process_result.exit_code,
            process_result.stdout,
            process_result.stderr,
            signal=process_result.signal,
            error_message="Run cancelled",
        )
    if process_result.timed_out:
        return _result(
            process_result.exit_code,
            process_result.stdout,
            process_result.stderr,
            timed_out=True,
            error_message=f"Timed out after {timeout_sec:g}s",
        )
    stdout_text = process_result.stdout.decode(errors="replace")
    stderr_text = process_result.stderr.decode(errors="replace")
    if stdout_text:
        await context.on_log("stdout", stdout_text)
    if stderr_text:
        await context.on_log("stderr", stderr_text)
    error = (
        None
        if process_result.exit_code == 0
        else f"Process exited with code {process_result.exit_code}"
    )
    return RuntimeExecutionResult(
        exit_code=process_result.exit_code,
        error_message=error,
        result_json={"stdout": stdout_text, "stderr": stderr_text},
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
    return RuntimeExecutionResult(
        exit_code=exit_code,
        signal=signal,
        timed_out=timed_out,
        error_message=error_message,
        result_json={
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
        },
    )
