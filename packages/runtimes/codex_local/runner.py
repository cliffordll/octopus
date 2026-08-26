from __future__ import annotations

import asyncio  # noqa: F401 -- retained for subprocess monkeypatch compatibility
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..context_env import apply_runtime_context_env
from ..environment import clear_inherited_blocking_proxy_env, resolve_runtime_executable
from ..instructions import runtime_prompt_from_config
from ..local_process import local_process_supervisor
from ..local_skills import (
    configure_managed_profile_env,
    desired_skills_from_config,
    ensure_octopus_cli_shim,
    materialize_runtime_skills,
)
from ..provider_config import apply_provider_env
from ..paths import ensure_managed_runtime_home
from ..session import effective_resume_session_id
from ..tool_capabilities import (
    append_runtime_tool_guidance,
    append_runtime_workspace_guidance,
)
from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .model_selection import CodexModelSelection


@dataclass(frozen=True)
class _RunAttempt:
    result: RuntimeExecutionResult
    stdout: str
    stderr: str
    raw_stderr: str


async def execute(context: RuntimeExecutionContext) -> RuntimeExecutionResult:
    command = resolve_runtime_executable(
        _string(context.config.get("command")) or "codex"
    )
    cwd = context.config.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("Codex adapter cwd must be a string")
    prompt = append_runtime_workspace_guidance(
        append_runtime_tool_guidance(
            runtime_prompt_from_config(context.config), "codex_local"
        ),
        context.workspace,
    )
    env = dict(os.environ)
    configured_env = context.config.get("env")
    explicit_env_keys: set[str] = set()
    if isinstance(configured_env, dict):
        explicit_env_keys = {key for key in configured_env if isinstance(key, str)}
        env.update(
            {
                key: value
                for key, value in configured_env.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        )
    if context.env:
        explicit_env_keys.update(context.env)
        env.update(context.env)
    apply_provider_env(
        env,
        context.config,
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
    )
    clear_inherited_blocking_proxy_env(env, explicit_keys=explicit_env_keys)
    configured_codex_home = _string(env.get("CODEX_HOME"))
    if configured_codex_home:
        env["CODEX_HOME"] = str(
            Path(configured_codex_home).expanduser().resolve()
            / "agents"
            / context.agent_id
        )
    else:
        env["CODEX_HOME"] = str(_default_codex_home(context))
    managed_home = await _prepare_managed_home(env, context.on_log)
    _prepare_managed_git_config(env)
    if managed_home is not None:
        ensure_octopus_cli_shim(env, managed_home)
    apply_runtime_context_env(env, context)
    materialize_runtime_skills(
        runtime_type="codex_local",
        config=context.config,
        desired_skills=desired_skills_from_config(context.config),
        skills_home=Path(env["CODEX_HOME"]) / "skills",
        location_label="managed CODEX_HOME/skills",
    )
    billing_type = _billing_type(env)
    biller = _biller(env, billing_type)
    loaded_skills = _loaded_skills(env)
    timeout = context.config.get("timeoutSec", 0)
    timeout_sec = float(timeout) if isinstance(timeout, (float, int)) else 0.0
    session_id = await effective_resume_session_id(
        context.config,
        cwd,
        runtime_label="Codex",
        on_log=context.on_log,
    )
    model_selection = CodexModelSelection.from_runtime_config(context.config)

    attempt = await _run_attempt(
        context=context,
        command=command,
        args=_build_args(context.config, session_id, model_selection),
        cwd=cwd,
        prompt=prompt,
        env=env,
        timeout_sec=timeout_sec,
        loaded_skills=loaded_skills,
        billing_type=billing_type,
        biller=biller,
    )
    using_default_model = False
    if (
        not attempt.result.timed_out
        and (attempt.result.exit_code or 0) != 0
        and model_selection.should_fallback(
            stdout=attempt.stdout,
            stderr=attempt.raw_stderr,
        )
    ):
        await context.on_log(
            "stderr",
            (
                f'[octopus] Codex model "{model_selection.model_id}" is unavailable; '
                "retrying with the Codex CLI default model.\n"
            ),
        )
        using_default_model = True
        attempt = await _run_attempt(
            context=context,
            command=command,
            args=_build_args(
                context.config,
                session_id,
                CodexModelSelection(None),
            ),
            cwd=cwd,
            prompt=prompt,
            env=env,
            timeout_sec=timeout_sec,
            loaded_skills=loaded_skills,
            billing_type=billing_type,
            biller=biller,
        )
    if (
        session_id
        and not attempt.result.timed_out
        and (attempt.result.exit_code or 0) != 0
        and _is_unknown_session_error(attempt.stdout, attempt.raw_stderr)
    ):
        await context.on_log(
            "stdout",
            (
                f'[octopus] Codex resume session "{session_id}" is unavailable; '
                "retrying with a fresh session.\n"
            ),
        )
        retry = await _run_attempt(
            context=context,
            command=command,
            args=_build_args(
                context.config,
                None,
                CodexModelSelection(None) if using_default_model else model_selection,
            ),
            cwd=cwd,
            prompt=prompt,
            env=env,
            timeout_sec=timeout_sec,
            loaded_skills=loaded_skills,
            billing_type=billing_type,
            biller=biller,
        )
        if retry.result.result_json is not None:
            retry.result.result_json["clearSession"] = (
                retry.result.session_id_after is None
            )
        return retry.result
    return attempt.result


async def _run_attempt(
    *,
    context: RuntimeExecutionContext,
    command: str,
    args: list[str],
    cwd: str | None,
    prompt: str,
    env: dict[str, str],
    timeout_sec: float,
    loaded_skills: list[dict[str, str | None]],
    billing_type: str,
    biller: str,
) -> _RunAttempt:
    live_output = _CodexLiveOutput(context)

    async def on_blocking_fallback(startup_error: PermissionError) -> None:
        await context.on_log(
            "stderr",
            (
                "[octopus] asyncio subprocess startup failed on Windows; "
                "retrying Codex CLI through the managed process fallback: "
                f"{startup_error}\n"
            ),
        )

    try:
        await context.on_log(
            "stdout", "[octopus] Codex CLI 已启动，正在等待运行时事件。\n"
        )
        process_result = await local_process_supervisor.run(
            command,
            *args,
            cwd=cwd,
            env=env,
            input_data=prompt.encode(),
            timeout_sec=timeout_sec,
            cancel_event=context.cancel_event,
            on_process_started=context.on_process_started,
            on_process_exited=context.on_process_exited,
            allow_blocking_fallback=True,
            on_blocking_fallback=on_blocking_fallback,
            on_stdout_chunk=live_output.on_stdout_chunk,
            on_stderr_chunk=live_output.on_stderr_chunk,
        )
    except OSError as exc:
        return _subprocess_start_error_attempt(
            exc,
            loaded_skills=loaded_skills,
            billing_type=billing_type,
            biller=biller,
        )
    await live_output.finish()
    if process_result.cancelled:
        stderr_text = _strip_benign_stderr(
            process_result.stderr.decode(errors="replace")
        )
        result = RuntimeExecutionResult(
            exit_code=process_result.exit_code,
            signal=process_result.signal,
            error_message="Run cancelled",
            result_json={
                "stdout": process_result.stdout.decode(errors="replace"),
                "stderr": stderr_text,
                "loadedSkills": loaded_skills,
                "billingType": billing_type,
                "biller": biller,
            },
        )
        return _RunAttempt(
            result=result,
            stdout=process_result.stdout.decode(errors="replace"),
            stderr=stderr_text,
            raw_stderr=process_result.stderr.decode(errors="replace"),
        )
    if process_result.timed_out:
        stderr_text = _strip_benign_stderr(
            process_result.stderr.decode(errors="replace")
        )
        result = RuntimeExecutionResult(
            exit_code=process_result.exit_code,
            timed_out=True,
            error_message=f"Timed out after {timeout_sec:g}s",
            result_json={
                "stdout": process_result.stdout.decode(errors="replace"),
                "stderr": stderr_text,
                "loadedSkills": loaded_skills,
                "billingType": billing_type,
                "biller": biller,
            },
        )
        return _RunAttempt(
            result=result,
            stdout=process_result.stdout.decode(errors="replace"),
            stderr=stderr_text,
            raw_stderr=process_result.stderr.decode(errors="replace"),
        )

    return await _completed_process_attempt(
        returncode=process_result.exit_code,
        stdout=process_result.stdout,
        stderr=process_result.stderr,
        timed_out=False,
        timeout_sec=timeout_sec,
        loaded_skills=loaded_skills,
        billing_type=billing_type,
        biller=biller,
    )


def _subprocess_start_error_attempt(
    exc: OSError,
    *,
    loaded_skills: list[dict[str, str | None]],
    billing_type: str,
    biller: str,
) -> _RunAttempt:
    message = str(exc) or exc.__class__.__name__
    result = RuntimeExecutionResult(
        exit_code=1,
        error_message=f"Failed to start Codex CLI: {message}",
        result_json={
            "stdout": "",
            "stderr": message,
            "loadedSkills": loaded_skills,
            "billingType": billing_type,
            "biller": biller,
        },
    )
    return _RunAttempt(result=result, stdout="", stderr=message, raw_stderr=message)


async def _completed_process_attempt(
    *,
    returncode: int | None,
    stdout: bytes,
    stderr: bytes,
    timed_out: bool,
    timeout_sec: float,
    loaded_skills: list[dict[str, str | None]],
    billing_type: str,
    biller: str,
) -> _RunAttempt:
    stdout_text = stdout.decode(errors="replace")
    stderr_text = _strip_benign_stderr(stderr.decode(errors="replace"))
    if timed_out:
        result = RuntimeExecutionResult(
            exit_code=returncode,
            timed_out=True,
            error_message=f"Timed out after {timeout_sec:g}s",
            result_json={
                "stdout": stdout_text,
                "stderr": stderr_text,
                "loadedSkills": loaded_skills,
                "billingType": billing_type,
                "biller": biller,
            },
        )
        return _RunAttempt(
            result=result,
            stdout=stdout_text,
            stderr=stderr_text,
            raw_stderr=stderr.decode(errors="replace"),
        )
    parsed = _parse_jsonl(stdout_text)
    error = None
    if returncode != 0:
        error = parsed["errorMessage"] or _first_line(stderr_text)
        error = error or f"Codex exited with code {returncode}"
    usage = {
        **parsed["usage"],
        "billingType": billing_type,
        "biller": biller,
    }
    result = RuntimeExecutionResult(
        exit_code=returncode,
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
    return _RunAttempt(
        result=result,
        stdout=stdout_text,
        stderr=stderr_text,
        raw_stderr=stderr.decode(errors="replace"),
    )


def _build_args(
    config: dict[str, Any],
    resume_session_id: str | None = None,
    model_selection: CodexModelSelection | None = None,
) -> list[str]:
    args = ["exec", "--skip-git-repo-check", "--json", "--disable", "plugins"]
    extra_args = config.get("extraArgs", config.get("args", []))
    normalized_extra_args = (
        list(extra_args)
        if isinstance(extra_args, list)
        and all(isinstance(argument, str) for argument in extra_args)
        else []
    )
    if config.get("search") is True:
        args.insert(0, "--search")
    if config.get("dangerouslyBypassApprovalsAndSandbox") is True:
        args.append("--dangerously-bypass-approvals-and-sandbox")
    elif not any(
        argument in {"--sandbox", "-s"} or argument.startswith(("--sandbox=", "-s="))
        for argument in normalized_extra_args
    ):
        # Agent Runs execute inside a system-managed workspace. Give the CLI
        # write access to that workspace without granting full host access.
        args.extend(["--sandbox", "workspace-write"])
    (model_selection or CodexModelSelection.from_runtime_config(config)).append_to(args)
    reasoning = _string(
        config.get("modelReasoningEffort") or config.get("reasoningEffort")
    )
    if reasoning:
        args.extend(["-c", f"model_reasoning_effort={json.dumps(reasoning)}"])
    args.extend(normalized_extra_args)
    args.extend(["-c", "skills.bundled.enabled=false"])
    if resume_session_id:
        args.extend(["resume", resume_session_id, "-"])
    else:
        args.append("-")
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


class _CodexLiveOutput:
    """Forward raw Codex output live and emit normalized progress events."""

    def __init__(self, context: RuntimeExecutionContext) -> None:
        self._context = context
        self._stdout = bytearray()
        self._stderr = bytearray()

    async def on_stdout_chunk(self, chunk: bytes) -> None:
        self._stdout.extend(chunk)
        await self._drain(self._stdout, stream="stdout")

    async def on_stderr_chunk(self, chunk: bytes) -> None:
        self._stderr.extend(chunk)
        await self._drain(self._stderr, stream="stderr")

    async def finish(self) -> None:
        await self._flush(self._stdout, stream="stdout")
        await self._flush(self._stderr, stream="stderr")

    async def _drain(self, buffer: bytearray, *, stream: str) -> None:
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                return
            line = bytes(buffer[: newline + 1])
            del buffer[: newline + 1]
            await self._emit_line(stream, line.decode(errors="replace"))

    async def _flush(self, buffer: bytearray, *, stream: str) -> None:
        if not buffer:
            return
        line = bytes(buffer).decode(errors="replace")
        buffer.clear()
        await self._emit_line(stream, line)

    async def _emit_line(self, stream: str, line: str) -> None:
        if stream == "stderr" and _is_benign_stderr_line(line):
            return
        await self._context.on_log(stream, line)
        if stream == "stdout":
            await _emit_codex_stream_event(self._context, line)


async def _emit_codex_stream_event(
    context: RuntimeExecutionContext, raw_line: str
) -> None:
    if context.on_stream_event is None:
        return
    try:
        event = json.loads(raw_line)
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict):
        return
    event_type = event.get("type")
    item = event.get("item")
    item = item if isinstance(item, dict) else {}
    if (
        event_type == "item.completed"
        and item.get("type") == "agent_message"
        and isinstance(item.get("text"), str)
        and item["text"]
    ):
        await context.on_stream_event(
            {"type": "assistant_delta", "delta": item["text"]}
        )
    message = _codex_progress_message(event_type, event, item)
    if message:
        await context.on_stream_event(
            {
                "type": "runtime_progress",
                "runtime": "codex_local",
                "eventType": event_type,
                "itemType": item.get("type"),
                "message": message,
            }
        )


def _codex_progress_message(
    event_type: object, event: dict[str, Any], item: dict[str, Any]
) -> str | None:
    if event_type == "thread.started":
        return "Codex 会话已启动"
    if event_type == "turn.started":
        return "Codex 开始处理任务"
    item_type = item.get("type")
    if event_type == "item.started" and item_type == "command_execution":
        command = _string(item.get("command"))
        return (
            f"正在执行命令：{_compact_progress_text(command)}"
            if command
            else "正在执行命令"
        )
    if event_type == "item.completed" and item_type == "command_execution":
        exit_code = item.get("exit_code")
        return (
            f"命令执行完成（退出码 {exit_code}）"
            if isinstance(exit_code, int)
            else "命令执行完成"
        )
    if event_type == "item.started" and item_type:
        return f"开始执行：{item_type}"
    if event_type == "item.completed" and item_type == "agent_message":
        return "Codex 已生成回复"
    if event_type == "item.completed" and item_type:
        return f"执行完成：{item_type}"
    if event_type == "turn.completed":
        return "Codex 本轮处理完成"
    if event_type in {"error", "turn.failed"}:
        raw_error = event.get("error")
        error = raw_error if isinstance(raw_error, dict) else {}
        message = _string(event.get("message")) or _string(error.get("message"))
        return (
            f"Codex 执行失败：{_compact_progress_text(message)}"
            if message
            else "Codex 执行失败"
        )
    return None


def _compact_progress_text(value: str | None, limit: int = 240) -> str:
    normalized = re.sub(r"\s+", " ", value or "").strip()
    return normalized if len(normalized) <= limit else f"{normalized[:limit].rstrip()}…"


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
    if _string(env.get("OPENROUTER_API_KEY")):
        return "openrouter"
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
    return ensure_managed_runtime_home(
        "codex_local", org_id=context.org_id, agent_id=context.agent_id
    )


async def _prepare_managed_home(env: dict[str, str], on_log: Any) -> Path | None:
    codex_home = _string(env.get("CODEX_HOME"))
    if not codex_home:
        return None
    codex_home_path = Path(codex_home).expanduser()
    managed_home = Path(codex_home).expanduser() / "home"
    managed_home.mkdir(parents=True, exist_ok=True)
    operator_home = _operator_home(env)
    linked = _sync_local_cli_credential_home_entries(operator_home, managed_home)
    linked_codex = _sync_local_codex_home_entries(operator_home, codex_home_path)
    env["HOME"] = str(managed_home)
    env["USERPROFILE"] = str(managed_home)
    configure_managed_profile_env(env, managed_home)
    env["OCTOPUS_OPERATOR_HOME"] = str(operator_home)
    env.pop("AGENT_HOME", None)
    env.pop("OCTOPUS_AGENT_ROOT", None)
    if linked:
        await on_log(
            "stdout",
            (
                f"[octopus] Shared {len(linked)} local CLI credential "
                f"entr{'y' if len(linked) == 1 else 'ies'} into managed HOME "
                f"{managed_home}: {', '.join(linked)}\n"
            ),
        )
    if linked_codex:
        await on_log(
            "stdout",
            (
                f"[octopus] Shared {len(linked_codex)} local Codex credential "
                f"entr{'y' if len(linked_codex) == 1 else 'ies'} into managed "
                f"CODEX_HOME {codex_home_path}: {', '.join(linked_codex)}\n"
            ),
        )
    return managed_home


def _prepare_managed_git_config(env: dict[str, str]) -> None:
    home = _string(env.get("HOME"))
    if not home:
        return
    git_config = Path(home).expanduser() / ".gitconfig"
    git_config.parent.mkdir(parents=True, exist_ok=True)
    git_config.write_text("[user]\n\tuseConfigOnly = true\n", encoding="utf-8")
    env["GIT_CONFIG_GLOBAL"] = str(git_config)
    _clear_unsafe_git_identity(env, "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL")
    _clear_unsafe_git_identity(env, "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")
    _append_git_config_env(env, "credential.helper", "")
    _append_git_config_env(env, "credential.helper", "!gh auth git-credential")


def _clear_unsafe_git_identity(
    env: dict[str, str], name_key: str, email_key: str
) -> None:
    email = _string(env.get(email_key))
    name = _string(env.get(name_key))
    if not email and not name:
        env.pop(name_key, None)
        env.pop(email_key, None)
        return
    if not email or email.lower().endswith(".local"):
        env.pop(name_key, None)
        env.pop(email_key, None)


def _append_git_config_env(env: dict[str, str], key: str, value: str) -> None:
    try:
        index = int(env.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        index = 0
    if index < 0:
        index = 0
    env[f"GIT_CONFIG_KEY_{index}"] = key
    env[f"GIT_CONFIG_VALUE_{index}"] = value
    env["GIT_CONFIG_COUNT"] = str(index + 1)


def _operator_home(env: dict[str, str]) -> Path:
    return Path(
        _string(env.get("OCTOPUS_OPERATOR_HOME"))
        or _string(os.environ.get("OCTOPUS_OPERATOR_HOME"))
        or _string(os.environ.get("HOME"))
        or _string(env.get("HOME"))
        or str(Path.home())
    ).expanduser()


_LOCAL_CLI_CREDENTIAL_HOME_ENTRIES = (
    ".aws",
    ".azure",
    ".config/gh",
    ".config/gcloud",
    ".config/op",
    ".config/vercel",
    ".config/configstore",
    ".docker",
    ".fly",
    ".git-credentials",
    ".gnupg",
    ".kube",
    ".netrc",
    ".npmrc",
    ".ssh",
    ".vercel",
    "Library/Application Support/gh",
    "Library/Application Support/com.heroku.cli",
)

_LOCAL_CODEX_HOME_CREDENTIAL_ENTRIES = (
    "auth.json",
    "cap_sid",
    "config.toml",
)


def _sync_local_codex_home_entries(
    source_home: Path, target_codex_home: Path
) -> list[str]:
    source_codex_home = source_home / ".codex"
    if _same_path(source_codex_home, target_codex_home):
        return []
    linked: list[str] = []
    for relative_entry in _LOCAL_CODEX_HOME_CREDENTIAL_ENTRIES:
        source = source_codex_home / relative_entry
        if not source.exists():
            continue
        target = target_codex_home / relative_entry
        if _ensure_link_or_copy(source, target):
            linked.append(relative_entry)
    return linked


def _sync_local_cli_credential_home_entries(
    source_home: Path, target_home: Path
) -> list[str]:
    if _same_path(source_home, target_home):
        return []
    linked: list[str] = []
    for relative_entry in _LOCAL_CLI_CREDENTIAL_HOME_ENTRIES:
        source = source_home / Path(relative_entry)
        if not source.exists():
            continue
        target = target_home / Path(relative_entry)
        if _ensure_link_or_copy(source, target):
            linked.append(relative_entry)
    return linked


def _ensure_link_or_copy(source: Path, target: Path) -> bool:
    if target.exists() or target.is_symlink():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source, target_is_directory=source.is_dir())
        return True
    except OSError:
        try:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            return True
        except OSError:
            return False


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(
            str(right.resolve())
        )
    except OSError:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
            os.path.abspath(str(right))
        )


def _runtime_session_id(config: dict[str, Any]) -> str | None:
    context = config.get("_octopus")
    if isinstance(context, dict):
        return _string(context.get("sessionIdBefore")) or _string(
            context.get("sessionId")
        )
    return _string(config.get("sessionIdBefore")) or _string(config.get("sessionId"))


def _is_unknown_session_error(stdout: str, stderr: str) -> bool:
    haystack = "\n".join(
        line.strip() for line in f"{stdout}\n{stderr}".splitlines() if line.strip()
    )
    return bool(
        re.search(
            (
                r"unknown (session|thread)|session .* not found|"
                r"thread .* not found|conversation .* not found|"
                r"missing rollout path for thread|state db missing rollout path|"
                r"no rollout found for thread id"
            ),
            haystack,
            re.IGNORECASE,
        )
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
