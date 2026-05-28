from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import AgentEnabledSkill


def _normalize_skill_keys(skill_keys: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for skill_key in skill_keys:
        value = skill_key.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


async def list_enabled_skill_keys(session: AsyncSession, agent_id: str) -> list[str]:
    rows = await session.execute(
        select(AgentEnabledSkill.skill_key)
        .where(AgentEnabledSkill.agent_id == agent_id)
        .order_by(AgentEnabledSkill.created_at, AgentEnabledSkill.skill_key)
    )
    return list(rows.scalars().all())


async def list_enabled_skill_keys_by_agent_ids(
    session: AsyncSession, agent_ids: Iterable[str]
) -> dict[str, list[str]]:
    ids = list(dict.fromkeys(agent_ids))
    if not ids:
        return {}
    rows = await session.execute(
        select(AgentEnabledSkill.agent_id, AgentEnabledSkill.skill_key)
        .where(AgentEnabledSkill.agent_id.in_(ids))
        .order_by(
            AgentEnabledSkill.agent_id,
            AgentEnabledSkill.created_at,
            AgentEnabledSkill.skill_key,
        )
    )
    result = {agent_id: [] for agent_id in ids}
    for agent_id, skill_key in rows.all():
        result.setdefault(agent_id, []).append(skill_key)
    return result


async def replace_enabled_skill_keys(
    session: AsyncSession, *, org_id: str, agent_id: str, skill_keys: Iterable[str]
) -> list[str]:
    normalized = _normalize_skill_keys(skill_keys)
    await session.execute(
        delete(AgentEnabledSkill).where(AgentEnabledSkill.agent_id == agent_id)
    )
    now = datetime.now(UTC)
    session.add_all(
        AgentEnabledSkill(
            org_id=org_id,
            agent_id=agent_id,
            skill_key=skill_key,
            created_at=now + timedelta(microseconds=index),
        )
        for index, skill_key in enumerate(normalized)
    )
    await session.flush()
    return normalized
