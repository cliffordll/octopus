from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
from datetime import UTC, datetime
from typing import Any

from ..types import RuntimeExecutionContext, RuntimeExecutionResult


class ProcessRuntimeAdapter:
    type = "process"

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        command = context.config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Process adapter missing command")
        args = _args(context.config.get("args"))
        cwd = context.config.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError("Process adapter cwd must be a string")
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
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if context.on_process_started is not None and process.pid is not None:
            await context.on_process_started(process.pid, datetime.now(UTC))
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
                    return RuntimeExecutionResult(
                        exit_code=process.returncode,
                        signal="SIGTERM",
                        error_message="Run cancelled",
                        result_json={
                            "stdout": stdout.decode(errors="replace"),
                            "stderr": stderr.decode(errors="replace"),
                        },
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
            return RuntimeExecutionResult(
                exit_code=process.returncode,
                timed_out=True,
                error_message=f"Timed out after {timeout_sec:g}s",
                result_json={
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                },
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


def _args(value: Any) -> list[str]:
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return []
