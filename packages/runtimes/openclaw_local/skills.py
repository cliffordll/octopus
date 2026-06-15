from __future__ import annotations

from pathlib import Path
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
        location_label="OpenClaw Claude-compatible skills home",
        skills_home=_openclaw_skills_home(config),
        materialize=materialize,
        external_detail="Detected outside this project's management in the OpenClaw skills home.",
    )


def _openclaw_skills_home(config: dict[str, Any]) -> Path:
    env = config.get("env")
    if isinstance(env, dict):
        home = env.get("HOME")
        if isinstance(home, str) and home.strip():
            return Path(home).expanduser().resolve() / ".claude" / "skills"
    return Path.home() / ".claude" / "skills"
