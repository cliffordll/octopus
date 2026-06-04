from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import tempfile
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
from ..provider_config import apply_provider_env
from ..tool_capabilities import (
    append_runtime_tool_guidance,
    append_runtime_workspace_guidance,
)
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
    command = resolve_runtime_executable(
        string(context.config.get("command")) or "claude"
    )
    cwd = context.config.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("Claude adapter cwd must be a string")
    prompt = append_runtime_workspace_guidance(
        append_runtime_tool_guidance(
            runtime_prompt_from_config(context.config), "claude_local"
        ),
        context.workspace,
    )
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
    apply_provider_env(
        env,
        context.config,
        api_key_env="ANTHROPIC_API_KEY",
        base_url_env="ANTHROPIC_BASE_URL",
    )
    await prepare_managed_home(
        runtime_type="claude_local",
        context=context,
        env=env,
    )
    apply_runtime_context_env(env, context)
    skills_root = Path(tempfile.mkdtemp(prefix="octopus-claude-skills-"))
    loaded_skills = materialize_runtime_skills(
        runtime_type="claude_local",
        config=context.config,
        desired_skills=desired_skills_from_config(context.config),
        skills_home=skills_root / ".claude" / "skills",
        location_label="temporary Claude skills home",
    )
    args.extend(["--add-dir", str(skills_root)])
    timeout = context.config.get("timeoutSec", 0)
    timeout_sec = float(timeout) if isinstance(timeout, (float, int)) else 0.0
    try:
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
                        loaded_skills=loaded_skills,
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
    finally:
        shutil.rmtree(skills_root, ignore_errors=True)

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
        result_json=_result_json(stdout_text, stderr_text, parsed, loaded_skills),
    )


def _result(
    exit_code: int | None,
    stdout: bytes,
    stderr: bytes,
    *,
    signal: str | None = None,
    timed_out: bool = False,
    error_message: str | None = None,
    loaded_skills: list[dict[str, str | None]] | None = None,
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
        result_json=_result_json(stdout_text, stderr_text, parsed, loaded_skills or []),
    )


def _result_json(
    stdout_text: str,
    stderr_text: str,
    parsed: dict,
    loaded_skills: list[dict[str, str | None]],
) -> dict:
    return {
        "stdout": stdout_text,
        "stderr": stderr_text,
        "summary": parsed["summary"],
        "model": parsed["model"],
        "costUsd": parsed["costUsd"],
        "loadedSkills": loaded_skills,
        "loginRequired": login_required(stdout_text, stderr_text, parsed["resultJson"]),
        "maxTurnsReached": max_turns(parsed["resultJson"]),
        "result": parsed["resultJson"],
    }
