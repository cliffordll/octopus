from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime

from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .protocol import args, configured_env


async def execute(context: RuntimeExecutionContext) -> RuntimeExecutionResult:
    command = context.config.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("Process adapter missing command")
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
    process = await asyncio.create_subprocess_exec(
        command,
        *process_args,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    pid = getattr(process, "pid", None)
    if context.on_process_started is not None and isinstance(pid, int):
        await context.on_process_started(pid, datetime.now(UTC))
    communication = asyncio.create_task(process.communicate())
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
    error = (
        None
        if process.returncode == 0
        else f"Process exited with code {process.returncode}"
    )
    return RuntimeExecutionResult(
        exit_code=process.returncode,
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
