from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import (
    ActivityLog,
    AgentEnabledSkill,
    HeartbeatRun,
    HeartbeatRunEvent,
)


class SkillUsageSource(NamedTuple):
    source_type: str
    created_at: datetime
    payload: dict
    run_id: str | None


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


async def add_enabled_skill_keys(
    session: AsyncSession, *, org_id: str, agent_id: str, skill_keys: Iterable[str]
) -> list[str]:
    current = await list_enabled_skill_keys(session, agent_id)
    return await replace_enabled_skill_keys(
        session,
        org_id=org_id,
        agent_id=agent_id,
        skill_keys=[*current, *_normalize_skill_keys(skill_keys)],
    )


async def list_skill_usage_sources(
    session: AsyncSession,
    *,
    org_id: str,
    agent_id: str,
    start_time: datetime,
) -> list[SkillUsageSource]:
    sources: list[SkillUsageSource] = []
    run_rows = await session.execute(
        select(HeartbeatRun).where(
            HeartbeatRun.org_id == org_id,
            HeartbeatRun.agent_id == agent_id,
            HeartbeatRun.created_at >= start_time,
        )
    )
    for row in run_rows.scalars().all():
        payload: dict = {}
        if isinstance(row.context_snapshot, dict):
            payload["context"] = row.context_snapshot
        if isinstance(row.result_json, dict):
            payload["result"] = row.result_json
        if isinstance(row.usage_json, dict):
            payload["usage"] = row.usage_json
        sources.append(SkillUsageSource("run", row.created_at, payload, row.id))

    event_rows = await session.execute(
        select(HeartbeatRunEvent).where(
            HeartbeatRunEvent.org_id == org_id,
            HeartbeatRunEvent.agent_id == agent_id,
            HeartbeatRunEvent.created_at >= start_time,
        )
    )
    for row in event_rows.scalars().all():
        if isinstance(row.payload, dict):
            sources.append(
                SkillUsageSource("run_event", row.created_at, row.payload, row.run_id)
            )

    activity_rows = await session.execute(
        select(ActivityLog).where(
            ActivityLog.org_id == org_id,
            ActivityLog.agent_id == agent_id,
            ActivityLog.created_at >= start_time,
        )
    )
    for row in activity_rows.scalars().all():
        if isinstance(row.details, dict):
            sources.append(
                SkillUsageSource("activity", row.created_at, row.details, row.run_id)
            )
    return sources
