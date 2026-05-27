from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import AgentWakeupRequest, HeartbeatRun, HeartbeatRunEvent


async def create_wakeup_request(
    session: AsyncSession, fields: Mapping[str, Any]
) -> AgentWakeupRequest:
    row = AgentWakeupRequest(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_wakeup_request(
    session: AsyncSession, wakeup_id: str, fields: Mapping[str, Any]
) -> AgentWakeupRequest | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(AgentWakeupRequest)
        .where(AgentWakeupRequest.id == wakeup_id)
        .values(**values)
        .returning(AgentWakeupRequest)
    )
    return result.scalar_one_or_none()


async def create_run(session: AsyncSession, fields: Mapping[str, Any]) -> HeartbeatRun:
    row = HeartbeatRun(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def get_run(session: AsyncSession, run_id: str) -> HeartbeatRun | None:
    return await session.get(HeartbeatRun, run_id)


async def list_runs(
    session: AsyncSession, org_id: str, agent_id: str | None = None
) -> Sequence[HeartbeatRun]:
    statement = select(HeartbeatRun).where(HeartbeatRun.org_id == org_id)
    if agent_id is not None:
        statement = statement.where(HeartbeatRun.agent_id == agent_id)
    result = await session.execute(
        statement.order_by(HeartbeatRun.created_at.desc(), HeartbeatRun.id.desc())
    )
    return result.scalars().all()


async def update_run(
    session: AsyncSession, run_id: str, fields: Mapping[str, Any]
) -> HeartbeatRun | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(HeartbeatRun)
        .where(HeartbeatRun.id == run_id)
        .values(**values)
        .returning(HeartbeatRun)
    )
    return result.scalar_one_or_none()


async def append_run_event(
    session: AsyncSession, fields: Mapping[str, Any]
) -> HeartbeatRunEvent:
    row = HeartbeatRunEvent(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def list_run_events(
    session: AsyncSession, run_id: str
) -> Sequence[HeartbeatRunEvent]:
    result = await session.execute(
        select(HeartbeatRunEvent)
        .where(HeartbeatRunEvent.run_id == run_id)
        .order_by(HeartbeatRunEvent.seq, HeartbeatRunEvent.id)
    )
    return result.scalars().all()
