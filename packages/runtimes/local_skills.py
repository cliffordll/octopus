from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from .skills import skill_snapshot_from_root


def desired_skills_from_config(config: dict[str, Any]) -> list[str]:
    context = config.get("_octopus")
    if isinstance(context, dict):
        desired = _string_list(context.get("desiredSkills"))
        if desired:
            return desired
    return _string_list(config.get("desiredSkills"))


def materialize_runtime_skills(
    *,
    runtime_type: str,
    config: dict[str, Any],
    desired_skills: list[str],
    skills_home: Path,
    location_label: str,
) -> list[dict[str, str | None]]:
    if not desired_skills:
        return []
    _clear_desired_targets(skills_home, desired_skills)
    snapshot = skill_snapshot_from_root(
        runtime_type=runtime_type,
        config=config,
        desired_skills=desired_skills,
        mode="ephemeral",
        location_label=location_label,
        skills_home=skills_home,
        materialize=True,
    )
    return [
        {
            "key": entry["key"],
            "runtimeName": entry["runtimeName"],
            "name": entry["key"],
            "description": entry.get("description"),
        }
        for entry in snapshot["entries"]
        if entry.get("desired") is True and isinstance(entry.get("runtimeName"), str)
    ]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def _clear_desired_targets(skills_home: Path, desired_skills: list[str]) -> None:
    for key in desired_skills:
        target = skills_home / key.removeprefix("agent:")
        if target.is_symlink() or target.is_file():
            target.unlink(missing_ok=True)
        elif target.exists():
            shutil.rmtree(target, ignore_errors=True)
