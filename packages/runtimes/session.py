from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


def runtime_session_id(config: dict[str, Any]) -> str | None:
    context = config.get("_octopus")
    if isinstance(context, dict):
        return _string(context.get("sessionIdBefore")) or _string(
            context.get("sessionId")
        )
    return _string(config.get("sessionIdBefore")) or _string(config.get("sessionId"))


def runtime_session_cwd(config: dict[str, Any]) -> str | None:
    context = config.get("_octopus")
    if isinstance(context, dict):
        return _string(context.get("sessionCwd")) or _string(context.get("cwd"))
    return _string(config.get("sessionCwd"))


async def effective_resume_session_id(
    config: dict[str, Any],
    cwd: str | None,
    *,
    runtime_label: str,
    on_log: Callable[[str, str], Awaitable[None]],
) -> str | None:
    session_id = runtime_session_id(config)
    if session_id is None:
        return None
    previous_cwd = runtime_session_cwd(config)
    if previous_cwd is None or cwd is None:
        return session_id
    if _same_path(previous_cwd, cwd):
        return session_id
    await on_log(
        "stdout",
        (
            f'[octopus] {runtime_label} resume session "{session_id}" was '
            f"created for cwd {previous_cwd}; current cwd is {cwd}. "
            "Starting a fresh session to avoid workspace mismatch.\n"
        ),
    )
    return None


def _same_path(left: str, right: str) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except OSError:
        return left == right


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
