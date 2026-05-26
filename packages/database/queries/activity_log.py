from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

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
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    return row
