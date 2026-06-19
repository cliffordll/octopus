from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import ensure_managed_runtime_home
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
        mode="persistent",
        location_label="managed CODEX_HOME/skills",
        skills_home=_codex_skills_home(config),
        materialize=materialize,
        installed_detail="Enabled for this agent and materialized into the managed Codex skills home.",
        missing_detail="Configured but not currently linked into the managed Codex skills home.",
        external_conflict_detail="Skill name is occupied by a non-managed entry inside the managed Codex skills home.",
        external_detail="Installed outside this project's management.",
        persistent_materialization=True,
    )


def _codex_skills_home(config: dict[str, Any]) -> Path:
    configured_home = _env_value(config, "CODEX_HOME")
    if configured_home:
        context = config.get("_octopus")
        agent_id = (
            _string(context.get("agentId")) if isinstance(context, dict) else None
        )
        base = Path(configured_home).expanduser().resolve()
        return base / "agents" / agent_id / "skills" if agent_id else base / "skills"
    context = config.get("_octopus")
    org_id = "default-org"
    agent_id = "default-agent"
    if isinstance(context, dict):
        org_id = _string(context.get("orgId")) or org_id
        agent_id = _string(context.get("agentId")) or agent_id
    return (
        ensure_managed_runtime_home("codex_local", org_id=org_id, agent_id=agent_id)
        / "skills"
    )


def _env_value(config: dict[str, Any], key: str) -> str | None:
    env = config.get("env")
    if isinstance(env, dict):
        return _string(env.get(key))
    return None


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
