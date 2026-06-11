from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select, update
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


async def get_wakeup_by_idempotency_key(
    session: AsyncSession, agent_id: str, idempotency_key: str
) -> AgentWakeupRequest | None:
    result = await session.execute(
        select(AgentWakeupRequest)
        .where(
            AgentWakeupRequest.agent_id == agent_id,
            AgentWakeupRequest.idempotency_key == idempotency_key,
        )
        .order_by(AgentWakeupRequest.requested_at.desc(), AgentWakeupRequest.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_wakeup_requests_by_status(
    session: AsyncSession, agent_id: str, status: str
) -> Sequence[AgentWakeupRequest]:
    result = await session.execute(
        select(AgentWakeupRequest)
        .where(
            AgentWakeupRequest.agent_id == agent_id,
            AgentWakeupRequest.status == status,
        )
        .order_by(AgentWakeupRequest.requested_at, AgentWakeupRequest.id)
    )
    return result.scalars().all()


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


async def list_running_run_ids(session: AsyncSession, agent_id: str) -> set[str]:
    result = await session.scalars(
        select(HeartbeatRun.id).where(
            HeartbeatRun.agent_id == agent_id,
            HeartbeatRun.status == "running",
        )
    )
    return set(result.all())


async def list_runs_by_status(
    session: AsyncSession, status: str
) -> Sequence[HeartbeatRun]:
    result = await session.execute(
        select(HeartbeatRun)
        .where(HeartbeatRun.status == status)
        .order_by(HeartbeatRun.created_at, HeartbeatRun.id)
    )
    return result.scalars().all()


async def list_queued_runs(
    session: AsyncSession, agent_id: str
) -> Sequence[HeartbeatRun]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(HeartbeatRun)
        .outerjoin(
            AgentWakeupRequest,
            HeartbeatRun.wakeup_request_id == AgentWakeupRequest.id,
        )
        .where(
            HeartbeatRun.agent_id == agent_id,
            HeartbeatRun.status == "queued",
            or_(
                HeartbeatRun.wakeup_request_id.is_(None),
                AgentWakeupRequest.requested_at <= now,
            ),
        )
        .order_by(HeartbeatRun.created_at, HeartbeatRun.id)
    )
    return result.scalars().all()


async def list_queued_agent_ids(session: AsyncSession) -> set[str]:
    result = await session.scalars(
        select(HeartbeatRun.agent_id)
        .outerjoin(
            AgentWakeupRequest,
            HeartbeatRun.wakeup_request_id == AgentWakeupRequest.id,
        )
        .where(
            HeartbeatRun.status == "queued",
            or_(
                HeartbeatRun.wakeup_request_id.is_(None),
                AgentWakeupRequest.requested_at <= datetime.now(UTC),
            ),
        )
        .distinct()
    )
    return set(result.all())


async def claim_queued_run(
    session: AsyncSession, run_id: str, started_at: datetime
) -> HeartbeatRun | None:
    result = await session.execute(
        update(HeartbeatRun)
        .where(HeartbeatRun.id == run_id, HeartbeatRun.status == "queued")
        .values(
            status="running",
            started_at=started_at,
            updated_at=started_at,
        )
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
    session: AsyncSession, run_id: str, after_seq: int = 0, limit: int = 200
) -> Sequence[HeartbeatRunEvent]:
    result = await session.execute(
        select(HeartbeatRunEvent)
        .where(
            HeartbeatRunEvent.run_id == run_id,
            HeartbeatRunEvent.seq > after_seq,
        )
        .order_by(HeartbeatRunEvent.seq, HeartbeatRunEvent.id)
        .limit(limit)
    )
    return result.scalars().all()
