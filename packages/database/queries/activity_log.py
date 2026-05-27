from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import ActivityLog


async def insert_activity_log(
    session: AsyncSession,
    *,
    org_id: str,
    actor_type: str,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    agent_id: str | None = None,
    run_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> ActivityLog:
    created_at = datetime.now(UTC)
    latest_created_at = await session.scalar(
        select(ActivityLog.created_at)
        .where(ActivityLog.org_id == org_id)
        .order_by(ActivityLog.created_at.desc())
        .limit(1)
    )
    if latest_created_at is not None and latest_created_at.tzinfo is None:
        latest_created_at = latest_created_at.replace(tzinfo=UTC)
    if latest_created_at is not None and created_at <= latest_created_at:
        created_at = latest_created_at + timedelta(microseconds=1)

    row = ActivityLog(
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        agent_id=agent_id,
        run_id=run_id,
        details=dict(details) if details is not None else None,
        created_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row
