from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import BudgetIncident, BudgetPolicy, CostEvent, HeartbeatRun


async def get_budget_policy(
    session: AsyncSession, policy_id: str
) -> BudgetPolicy | None:
    return await session.get(BudgetPolicy, policy_id)


async def find_budget_policy(
    session: AsyncSession,
    *,
    org_id: str,
    scope_type: str,
    scope_id: str,
    metric: str,
    window_kind: str,
) -> BudgetPolicy | None:
    result = await session.execute(
        select(BudgetPolicy).where(
            BudgetPolicy.org_id == org_id,
            BudgetPolicy.scope_type == scope_type,
            BudgetPolicy.scope_id == scope_id,
            BudgetPolicy.metric == metric,
            BudgetPolicy.window_kind == window_kind,
        )
    )
    return result.scalar_one_or_none()


async def list_budget_policies(
    session: AsyncSession, org_id: str
) -> Sequence[BudgetPolicy]:
    result = await session.execute(
        select(BudgetPolicy)
        .where(BudgetPolicy.org_id == org_id)
        .order_by(BudgetPolicy.updated_at.desc(), BudgetPolicy.id.desc())
    )
    return result.scalars().all()


async def create_budget_policy(
    session: AsyncSession, fields: Mapping[str, Any]
) -> BudgetPolicy:
    row = BudgetPolicy(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_budget_policy(
    session: AsyncSession, policy_id: str, fields: Mapping[str, Any]
) -> BudgetPolicy | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(BudgetPolicy)
        .where(BudgetPolicy.id == policy_id)
        .values(**values)
        .returning(BudgetPolicy)
    )
    return result.scalar_one_or_none()


async def observed_budget_amount(
    session: AsyncSession,
    policy: BudgetPolicy,
    *,
    window_start: datetime,
    window_end: datetime,
) -> int:
    statement = select(func.coalesce(func.sum(CostEvent.cost_cents), 0)).where(
        CostEvent.org_id == policy.org_id
    )
    if policy.scope_type == "agent":
        statement = statement.where(CostEvent.agent_id == policy.scope_id)
    elif policy.scope_type == "project":
        statement = statement.where(CostEvent.project_id == policy.scope_id)
    if policy.window_kind == "calendar_month_utc":
        statement = statement.where(
            CostEvent.occurred_at >= window_start,
            CostEvent.occurred_at < window_end,
        )
    result = await session.execute(statement)
    return int(result.scalar_one() or 0)


async def get_open_budget_incident(
    session: AsyncSession,
    *,
    policy_id: str,
    window_start: datetime,
    threshold_type: str,
) -> BudgetIncident | None:
    result = await session.execute(
        select(BudgetIncident).where(
            BudgetIncident.policy_id == policy_id,
            BudgetIncident.window_start == window_start,
            BudgetIncident.threshold_type == threshold_type,
            BudgetIncident.status == "open",
        )
    )
    return result.scalar_one_or_none()


async def create_budget_incident(
    session: AsyncSession, fields: Mapping[str, Any]
) -> BudgetIncident:
    row = BudgetIncident(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def list_open_budget_incidents(
    session: AsyncSession, org_id: str
) -> Sequence[BudgetIncident]:
    result = await session.execute(
        select(BudgetIncident)
        .where(BudgetIncident.org_id == org_id, BudgetIncident.status == "open")
        .order_by(BudgetIncident.created_at.desc(), BudgetIncident.id.desc())
    )
    return result.scalars().all()


async def get_budget_incident(
    session: AsyncSession, incident_id: str
) -> BudgetIncident | None:
    return await session.get(BudgetIncident, incident_id)


async def resolve_open_budget_incidents_for_policy(
    session: AsyncSession,
    policy_id: str,
    *,
    status: str,
) -> None:
    await session.execute(
        update(BudgetIncident)
        .where(BudgetIncident.policy_id == policy_id, BudgetIncident.status == "open")
        .values(
            status=status, resolved_at=datetime.now(UTC), updated_at=datetime.now(UTC)
        )
    )


async def resolve_budget_incident(
    session: AsyncSession, incident_id: str, *, status: str
) -> BudgetIncident | None:
    now = datetime.now(UTC)
    result = await session.execute(
        update(BudgetIncident)
        .where(BudgetIncident.id == incident_id)
        .values(status=status, resolved_at=now, updated_at=now)
        .returning(BudgetIncident)
    )
    return result.scalar_one_or_none()


async def list_budget_scope_runs(
    session: AsyncSession,
    *,
    org_id: str,
    scope_type: str,
    scope_id: str,
) -> Sequence[HeartbeatRun]:
    statement = select(HeartbeatRun).where(
        HeartbeatRun.org_id == org_id,
        HeartbeatRun.status.in_(("queued", "running")),
    )
    if scope_type == "agent":
        statement = statement.where(HeartbeatRun.agent_id == scope_id)
    elif scope_type == "project":
        statement = statement.where(
            HeartbeatRun.context_snapshot["projectId"].as_string() == scope_id
        )
    result = await session.execute(statement)
    return result.scalars().all()


async def list_relevant_budget_policies(
    session: AsyncSession,
    *,
    org_id: str,
    agent_id: str | None,
    project_id: str | None,
) -> Sequence[BudgetPolicy]:
    filters = [
        BudgetPolicy.org_id == org_id,
        BudgetPolicy.is_active.is_(True),
        BudgetPolicy.metric == "billed_cents",
    ]
    scope_filters = [
        and_(BudgetPolicy.scope_type == "organization", BudgetPolicy.scope_id == org_id)
    ]
    if agent_id is not None:
        scope_filters.append(
            and_(BudgetPolicy.scope_type == "agent", BudgetPolicy.scope_id == agent_id)
        )
    if project_id is not None:
        scope_filters.append(
            and_(
                BudgetPolicy.scope_type == "project",
                BudgetPolicy.scope_id == project_id,
            )
        )
    result = await session.execute(
        select(BudgetPolicy).where(*filters, or_(*scope_filters))
    )
    return result.scalars().all()
