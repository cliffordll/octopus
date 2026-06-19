from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from ..skills import skill_snapshot_from_root


def skill_snapshot(
    *,
    runtime_type: str,
    config: dict[str, Any],
    desired_skills: list[str],
    materialize: bool,
) -> dict[str, Any]:
    return skill_snapshot_from_root(
        runtime_type=runtime_type,
        config=config,
        desired_skills=desired_skills,
        mode="ephemeral",
        location_label="OpenClaw agent workspace skills",
        skills_home=_openclaw_skills_home(config),
        materialize=materialize,
        external_detail="Detected outside this project's management in the OpenClaw skills home.",
    )


def _openclaw_skills_home(config: dict[str, Any]) -> Path:
    env = config.get("env")
    home: str | None = None
    if isinstance(env, dict):
        value = env.get("HOME")
        if isinstance(value, str) and value.strip():
            home = value
    context = config.get("_octopus")
    agent_id = None
    if isinstance(context, dict):
        agent_id = context.get("agentId")
    workspace = _openclaw_workspace_path(
        Path(home).expanduser().resolve() if home else Path.home(),
        agent_id if isinstance(agent_id, str) else None,
    )
    return workspace / "skills"


def _openclaw_workspace_path(home: Path, agent_id: str | None) -> Path:
    normalized = _normalize_openclaw_agent_id(agent_id)
    if normalized == "main":
        return home / ".openclaw" / "workspace"
    return home / ".openclaw" / f"workspace-{normalized}"


def _normalize_openclaw_agent_id(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "main"
    normalized = raw.lower()
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", raw, flags=re.IGNORECASE):
        return normalized
    normalized = re.sub(r"[^a-z0-9_-]+", "-", normalized).strip("-")
    return normalized[:64] or "main"
