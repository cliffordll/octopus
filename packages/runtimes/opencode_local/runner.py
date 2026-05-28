from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime

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
    command = string(context.config.get("command")) or "opencode"
    cwd = context.config.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("OpenCode adapter cwd must be a string")
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
    home = await prepare_managed_home(
        runtime_type="opencode_local",
        context=context,
        env=env,
    )
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
                    model=string(context.config.get("model")),
                    loaded_skills=loaded_skills,
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
            model=string(context.config.get("model")),
            loaded_skills=loaded_skills,
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
    stdout: bytes,
    stderr: bytes,
    *,
    signal: str | None = None,
    timed_out: bool = False,
    error_message: str | None = None,
    model: str | None = None,
    loaded_skills: list[dict[str, str | None]] | None = None,
) -> RuntimeExecutionResult:
    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
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
