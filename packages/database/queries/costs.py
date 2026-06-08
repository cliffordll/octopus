from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Agent, CostEvent, Organization


async def create_cost_event(
    session: AsyncSession, fields: Mapping[str, Any]
) -> CostEvent:
    row = CostEvent(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def list_cost_events(
    session: AsyncSession,
    org_id: str,
    *,
    agent_id: str | None = None,
    project_id: str | None = None,
    provider: str | None = None,
    biller: str | None = None,
    model: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int | None = None,
) -> Sequence[CostEvent]:
    statement = select(CostEvent).where(CostEvent.org_id == org_id)
    if agent_id is not None:
        statement = statement.where(CostEvent.agent_id == agent_id)
    if project_id is not None:
        statement = statement.where(CostEvent.project_id == project_id)
    if provider is not None:
        statement = statement.where(CostEvent.provider == provider)
    if biller is not None:
        statement = statement.where(CostEvent.biller == biller)
    if model is not None:
        statement = statement.where(CostEvent.model == model)
    if start_time is not None:
        statement = statement.where(CostEvent.occurred_at >= start_time)
    if end_time is not None:
        statement = statement.where(CostEvent.occurred_at <= end_time)
    statement = statement.order_by(CostEvent.occurred_at.desc(), CostEvent.id.desc())
    if limit is not None:
        statement = statement.limit(limit)
    result = await session.execute(statement)
    return result.scalars().all()


async def increment_organization_spend(
    session: AsyncSession, org_id: str, cost_cents: int
) -> None:
    await session.execute(
        update(Organization)
        .where(Organization.id == org_id)
        .values(
            spent_monthly_cents=Organization.spent_monthly_cents + cost_cents,
            updated_at=datetime.now(UTC),
        )
    )


async def increment_agent_spend(
    session: AsyncSession, agent_id: str, cost_cents: int
) -> None:
    await session.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(
            spent_monthly_cents=Agent.spent_monthly_cents + cost_cents,
            updated_at=datetime.now(UTC),
        )
    )
