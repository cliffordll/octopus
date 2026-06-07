from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Agent
from ._compat import update_returning_one


async def list_org_agents(session: AsyncSession, org_id: str) -> Sequence[Agent]:
    result = await session.execute(
        select(Agent).where(Agent.org_id == org_id).order_by(Agent.created_at, Agent.id)
    )
    return result.scalars().all()


async def get_agent_by_id(session: AsyncSession, agent_id: str) -> Agent | None:
    result = await session.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def create_agent(session: AsyncSession, fields: Mapping[str, Any]) -> Agent:
    row = Agent(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_agent(
    session: AsyncSession, agent_id: str, fields: Mapping[str, Any]
) -> Agent | None:
    if not fields:
        return await get_agent_by_id(session, agent_id)
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(session, Agent, Agent.id == agent_id, values)
