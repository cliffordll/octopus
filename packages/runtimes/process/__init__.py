from __future__ import annotations

import asyncio
import os
import shlex
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
        try:
            if timeout_sec > 0:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_sec
                )
            else:
                stdout, stderr = await process.communicate()
        except TimeoutError:
            process.kill()
            stdout, stderr = await process.communicate()
            return RuntimeExecutionResult(
                exit_code=process.returncode,
                timed_out=True,
                error_message=f"Timed out after {timeout_sec:g}s",
                result_json={
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                },
            )
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
