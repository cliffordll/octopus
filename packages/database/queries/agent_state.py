from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import AgentConfigRevision, AgentRuntimeState, AgentTaskSession


async def create_config_revision(
    session: AsyncSession, fields: Mapping[str, Any]
) -> AgentConfigRevision:
    row = AgentConfigRevision(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def list_config_revisions(
    session: AsyncSession, agent_id: str
) -> Sequence[AgentConfigRevision]:
    result = await session.execute(
        select(AgentConfigRevision)
        .where(AgentConfigRevision.agent_id == agent_id)
        .order_by(AgentConfigRevision.created_at.desc(), AgentConfigRevision.id.desc())
    )
    return result.scalars().all()


async def get_config_revision(
    session: AsyncSession, agent_id: str, revision_id: str
) -> AgentConfigRevision | None:
    result = await session.execute(
        select(AgentConfigRevision).where(
            AgentConfigRevision.agent_id == agent_id,
            AgentConfigRevision.id == revision_id,
        )
    )
    return result.scalar_one_or_none()


async def get_runtime_state(
    session: AsyncSession, agent_id: str
) -> AgentRuntimeState | None:
    return await session.get(AgentRuntimeState, agent_id)


async def create_runtime_state(
    session: AsyncSession, fields: Mapping[str, Any]
) -> AgentRuntimeState:
    row = AgentRuntimeState(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_runtime_state(
    session: AsyncSession, agent_id: str, fields: Mapping[str, Any]
) -> AgentRuntimeState | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(AgentRuntimeState)
        .where(AgentRuntimeState.agent_id == agent_id)
        .values(**values)
        .returning(AgentRuntimeState)
    )
    return result.scalar_one_or_none()


async def list_task_sessions(
    session: AsyncSession, agent_id: str
) -> Sequence[AgentTaskSession]:
    result = await session.execute(
        select(AgentTaskSession)
        .where(AgentTaskSession.agent_id == agent_id)
        .order_by(
            AgentTaskSession.updated_at.desc(), AgentTaskSession.created_at.desc()
        )
    )
    return result.scalars().all()


async def delete_task_sessions(
    session: AsyncSession,
    *,
    org_id: str,
    agent_id: str,
    task_key: str | None = None,
    agent_runtime_type: str | None = None,
) -> int:
    statement = delete(AgentTaskSession).where(
        AgentTaskSession.org_id == org_id, AgentTaskSession.agent_id == agent_id
    )
    if task_key is not None:
        statement = statement.where(AgentTaskSession.task_key == task_key)
    if agent_runtime_type is not None:
        statement = statement.where(
            AgentTaskSession.agent_runtime_type == agent_runtime_type
        )
    result = await session.execute(statement.returning(AgentTaskSession.id))
    return len(result.scalars().all())
