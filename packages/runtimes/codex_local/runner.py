from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..types import RuntimeExecutionContext, RuntimeExecutionResult


async def execute(context: RuntimeExecutionContext) -> RuntimeExecutionResult:
    command = _string(context.config.get("command")) or "codex"
    cwd = context.config.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("Codex adapter cwd must be a string")
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
    if context.env:
        env.update(context.env)
    if not _string(env.get("CODEX_HOME")):
        env["CODEX_HOME"] = str(_default_codex_home(context))
    billing_type = _billing_type(env)
    biller = _biller(env, billing_type)
    loaded_skills = _loaded_skills(env)
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
                stderr_text = _strip_benign_stderr(stderr.decode(errors="replace"))
                return RuntimeExecutionResult(
                    exit_code=process.returncode,
                    signal="SIGTERM",
                    error_message="Run cancelled",
                    result_json={
                        "stdout": stdout.decode(errors="replace"),
                        "stderr": stderr_text,
                        "loadedSkills": loaded_skills,
                        "billingType": billing_type,
                        "biller": biller,
                    },
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
        stderr_text = _strip_benign_stderr(stderr.decode(errors="replace"))
        return RuntimeExecutionResult(
            exit_code=process.returncode,
            timed_out=True,
            error_message=f"Timed out after {timeout_sec:g}s",
            result_json={
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr_text,
                "loadedSkills": loaded_skills,
                "billingType": billing_type,
                "biller": biller,
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
    stderr_text = _strip_benign_stderr(stderr.decode(errors="replace"))
    if stdout_text:
        await context.on_log("stdout", stdout_text)
    if stderr_text:
        await context.on_log("stderr", stderr_text)
    parsed = _parse_jsonl(stdout_text)
    error = None
    if process.returncode != 0:
        error = parsed["errorMessage"] or _first_line(stderr_text)
        error = error or f"Codex exited with code {process.returncode}"
    usage = {
        **parsed["usage"],
        "billingType": billing_type,
        "biller": biller,
    }
    return RuntimeExecutionResult(
        exit_code=process.returncode,
        error_message=error,
        usage_json=usage,
        session_id_after=parsed["sessionId"],
        result_json={
            "stdout": stdout_text,
            "stderr": stderr_text,
            "summary": parsed["summary"],
            "loadedSkills": loaded_skills,
            "billingType": billing_type,
            "biller": biller,
        },
    )


def _build_args(config: dict[str, Any]) -> list[str]:
    args = ["exec", "--json", "--disable", "plugins"]
    if config.get("search") is True:
        args.insert(0, "--search")
    if config.get("dangerouslyBypassApprovalsAndSandbox") is True:
        args.append("--dangerously-bypass-approvals-and-sandbox")
    model = _string(config.get("model"))
    if model:
        args.extend(["--model", model])
    reasoning = _string(
        config.get("modelReasoningEffort") or config.get("reasoningEffort")
    )
    if reasoning:
        args.extend(["-c", f"model_reasoning_effort={json.dumps(reasoning)}"])
    extra_args = config.get("extraArgs", config.get("args", []))
    if isinstance(extra_args, list) and all(
        isinstance(argument, str) for argument in extra_args
    ):
        args.extend(extra_args)
    args.extend(["-c", "skills.bundled.enabled=false", "-"])
    return args


def _parse_jsonl(stdout: str) -> dict[str, Any]:
    session_id: str | None = None
    messages: list[str] = []
    error_message: str | None = None
    usage = {"inputTokens": 0, "cachedInputTokens": 0, "outputTokens": 0}
    for raw_line in stdout.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "thread.started" and isinstance(event.get("thread_id"), str):
            session_id = event["thread_id"]
        elif event_type == "error" and isinstance(event.get("message"), str):
            message = event["message"].strip()
            if message and not _is_closed_stdin_tool_session_error(message):
                error_message = message
        elif event_type == "item.completed":
            item = event.get("item")
            if (
                isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
            ):
                messages.append(item["text"])
        elif event_type == "turn.completed":
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                usage = {
                    "inputTokens": _integer(raw_usage.get("input_tokens")),
                    "cachedInputTokens": _integer(raw_usage.get("cached_input_tokens")),
                    "outputTokens": _integer(raw_usage.get("output_tokens")),
                }
        elif event_type == "turn.failed":
            raw_error = event.get("error")
            if isinstance(raw_error, dict) and isinstance(
                raw_error.get("message"), str
            ):
                message = raw_error["message"].strip()
                if message and not _is_closed_stdin_tool_session_error(message):
                    error_message = message
    return {
        "sessionId": session_id,
        "summary": "\n\n".join(messages).strip(),
        "usage": usage,
        "errorMessage": error_message,
    }


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _first_line(value: str) -> str | None:
    return next((line.strip() for line in value.splitlines() if line.strip()), None)


_BENIGN_STDERR_PATTERNS = (
    re.compile(r"telemetry", re.IGNORECASE),
    re.compile(r"analytics", re.IGNORECASE),
)


def _strip_benign_stderr(value: str) -> str:
    if not value:
        return value
    return "".join(
        line
        for line in value.splitlines(keepends=True)
        if not _is_benign_stderr_line(line)
    )


def _is_benign_stderr_line(line: str) -> bool:
    text = line.strip()
    return bool(text) and any(
        pattern.search(text) for pattern in _BENIGN_STDERR_PATTERNS
    )


_CLOSED_STDIN_TOOL_SESSION_PATTERNS = (
    re.compile(r"\bwrite_stdin\b[\s\S]*\bstdin is closed\b", re.IGNORECASE),
    re.compile(
        r"\brerun exec_command with tty=true to keep stdin open\b", re.IGNORECASE
    ),
)


def _is_closed_stdin_tool_session_error(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value).strip()
    return any(
        pattern.search(normalized) for pattern in _CLOSED_STDIN_TOOL_SESSION_PATTERNS
    )


def _billing_type(env: dict[str, str]) -> str:
    return "api" if _string(env.get("OPENAI_API_KEY")) else "subscription"


def _biller(env: dict[str, str], billing_type: str) -> str:
    base_url = (
        _string(env.get("OPENAI_BASE_URL"))
        or _string(env.get("OPENAI_API_BASE"))
        or _string(env.get("OPENAI_API_BASE_URL"))
        or ""
    )
    if "openrouter.ai" in base_url.lower():
        return "openrouter"
    return "chatgpt" if billing_type == "subscription" else "openai"


def _default_codex_home(context: RuntimeExecutionContext) -> Path:
    return (
        Path.cwd()
        / ".octopus"
        / "runtime-homes"
        / "codex_local"
        / context.org_id
        / context.agent_id
    )


def _loaded_skills(env: dict[str, str]) -> list[dict[str, str | None]]:
    codex_home = _string(env.get("CODEX_HOME"))
    if not codex_home:
        return []
    skills_home = Path(codex_home).expanduser() / "skills"
    if not skills_home.exists() or not skills_home.is_dir():
        return []
    loaded: list[dict[str, str | None]] = []
    for skill_dir in sorted(skills_home.iterdir(), key=lambda item: item.name):
        skill_file = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_file.is_file():
            continue
        name, description = _skill_metadata(skill_file, skill_dir.name)
        loaded.append(
            {
                "key": skill_dir.name,
                "runtimeName": skill_dir.name,
                "name": name,
                "description": description,
            }
        )
    return loaded


def _skill_metadata(skill_file: Path, fallback_name: str) -> tuple[str, str | None]:
    try:
        lines = skill_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return fallback_name, None
    headings: list[str] = []
    for line in lines:
        value = line.strip()
        if not value:
            continue
        if value.startswith("#"):
            heading = value.lstrip("#").strip()
            if heading:
                headings.append(heading)
            continue
        return (headings[0] if headings else fallback_name), value
    return (headings[0] if headings else fallback_name), None
