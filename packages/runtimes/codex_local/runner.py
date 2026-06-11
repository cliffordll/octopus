from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..common import runtime_subprocess_kwargs
from ..context_env import apply_runtime_context_env
from ..environment import clear_inherited_blocking_proxy_env, resolve_runtime_executable
from ..instructions import runtime_prompt_from_config
from ..local_skills import configure_managed_profile_env
from ..provider_config import apply_provider_env, model_for_cli
from ..paths import ensure_managed_runtime_home
from ..session import effective_resume_session_id
from ..tool_capabilities import (
    append_runtime_tool_guidance,
    append_runtime_workspace_guidance,
)
from ..types import RuntimeExecutionContext, RuntimeExecutionResult


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
    if not _string(env.get("CODEX_HOME")):
        env["CODEX_HOME"] = str(_default_codex_home(context))
    await _prepare_managed_home(env, context.on_log)
    _prepare_managed_git_config(env)
    apply_runtime_context_env(env, context)
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

    attempt = await _run_attempt(
        context=context,
        command=command,
        args=_build_args(context.config, session_id),
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
            args=_build_args(context.config, None),
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
    try:
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **runtime_subprocess_kwargs(),
        )
    except PermissionError as exc:
        if _should_retry_with_blocking_subprocess(exc):
            return await _run_blocking_subprocess_attempt(
                context=context,
                command=command,
                args=args,
                cwd=cwd,
                prompt=prompt,
                env=env,
                timeout_sec=timeout_sec,
                loaded_skills=loaded_skills,
                billing_type=billing_type,
                biller=biller,
                startup_error=exc,
            )
        return _subprocess_start_error_attempt(
            exc,
            loaded_skills=loaded_skills,
            billing_type=billing_type,
            biller=biller,
        )
    except OSError as exc:
        return _subprocess_start_error_attempt(
            exc,
            loaded_skills=loaded_skills,
            billing_type=billing_type,
            biller=biller,
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
                result = RuntimeExecutionResult(
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
                return _RunAttempt(
                    result=result,
                    stdout=stdout.decode(errors="replace"),
                    stderr=stderr_text,
                    raw_stderr=stderr.decode(errors="replace"),
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
        result = RuntimeExecutionResult(
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
        return _RunAttempt(
            result=result,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr_text,
            raw_stderr=stderr.decode(errors="replace"),
        )
    except asyncio.CancelledError:
        communication.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await communication
        process.kill()
        await process.communicate()
        await process.wait()
        raise

    return await _completed_process_attempt(
        context=context,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
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


def _should_retry_with_blocking_subprocess(_: PermissionError) -> bool:
    return os.name == "nt"


async def _run_blocking_subprocess_attempt(
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
    startup_error: PermissionError,
) -> _RunAttempt:
    await context.on_log(
        "stderr",
        (
            "[octopus] asyncio subprocess startup failed on Windows; "
            f"retrying Codex CLI with blocking subprocess fallback: {startup_error}\n"
        ),
    )
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            [command, *args],
            cwd=cwd,
            env=env,
            input=prompt.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec if timeout_sec > 0 else None,
            **runtime_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or b""
        stderr = exc.stderr or b""
        return await _completed_process_attempt(
            context=context,
            returncode=1,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            timeout_sec=timeout_sec,
            loaded_skills=loaded_skills,
            billing_type=billing_type,
            biller=biller,
        )
    except OSError as exc:
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

    return await _completed_process_attempt(
        context=context,
        returncode=completed.returncode,
        stdout=completed.stdout or b"",
        stderr=completed.stderr or b"",
        timed_out=False,
        timeout_sec=timeout_sec,
        loaded_skills=loaded_skills,
        billing_type=billing_type,
        biller=biller,
    )


async def _completed_process_attempt(
    *,
    context: RuntimeExecutionContext,
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
    await _emit_codex_stream_events_from_text(context, stdout_text)
    if stdout_text:
        await context.on_log("stdout", stdout_text)
    if stderr_text:
        await context.on_log("stderr", stderr_text)
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
    config: dict[str, Any], resume_session_id: str | None = None
) -> list[str]:
    args = ["exec", "--json", "--disable", "plugins"]
    if config.get("search") is True:
        args.insert(0, "--search")
    if config.get("dangerouslyBypassApprovalsAndSandbox") is True:
        args.append("--dangerously-bypass-approvals-and-sandbox")
    model = model_for_cli(config)
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


async def _emit_codex_stream_events_from_text(
    context: RuntimeExecutionContext, stdout_text: str
) -> None:
    if context.on_stream_event is None:
        return
    for raw_line in stdout_text.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if (
            isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
            and item["text"]
        ):
            await context.on_stream_event(
                {"type": "assistant_delta", "delta": item["text"]}
            )


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


async def _prepare_managed_home(env: dict[str, str], on_log: Any) -> None:
    codex_home = _string(env.get("CODEX_HOME"))
    if not codex_home:
        return
    managed_home = Path(codex_home).expanduser() / "home"
    managed_home.mkdir(parents=True, exist_ok=True)
    operator_home = _operator_home(env)
    linked = _sync_local_cli_credential_home_entries(operator_home, managed_home)
    env["HOME"] = str(managed_home)
    env["USERPROFILE"] = str(managed_home)
    configure_managed_profile_env(env, managed_home)
    env["OCTOPUS_OPERATOR_HOME"] = str(operator_home)
    env.pop("AGENT_HOME", None)
    env.pop("RUDDER_AGENT_ROOT", None)
    if linked:
        await on_log(
            "stdout",
            (
                f"[octopus] Shared {len(linked)} local CLI credential "
                f"entr{'y' if len(linked) == 1 else 'ies'} into managed HOME "
                f"{managed_home}: {', '.join(linked)}\n"
            ),
        )


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
        _string(env.get("RUDDER_OPERATOR_HOME"))
        or _string(os.environ.get("RUDDER_OPERATOR_HOME"))
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
