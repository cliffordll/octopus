from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Goal, ProjectGoal
from ._compat import delete_returning_one, update_returning_one


async def list_org_goals(session: AsyncSession, org_id: str) -> Sequence[Goal]:
    result = await session.execute(
        select(Goal).where(Goal.org_id == org_id).order_by(Goal.created_at, Goal.id)
    )
    return result.scalars().all()


async def get_goal_by_id(session: AsyncSession, goal_id: str) -> Goal | None:
    result = await session.execute(select(Goal).where(Goal.id == goal_id))
    return result.scalar_one_or_none()


async def create_goal(session: AsyncSession, fields: Mapping[str, Any]) -> Goal:
    row = Goal(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_goal(
    session: AsyncSession, goal_id: str, fields: Mapping[str, Any]
) -> Goal | None:
    if not fields:
        return await get_goal_by_id(session, goal_id)
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(session, Goal, Goal.id == goal_id, values)


async def delete_goal(session: AsyncSession, goal_id: str) -> Goal | None:
    return await delete_returning_one(session, Goal, Goal.id == goal_id)


async def list_project_goals(session: AsyncSession, project_id: str) -> Sequence[Goal]:
    result = await session.execute(
        select(Goal)
        .join(ProjectGoal, ProjectGoal.goal_id == Goal.id)
        .where(ProjectGoal.project_id == project_id)
        .order_by(ProjectGoal.created_at, Goal.id)
    )
    return result.scalars().all()


async def replace_project_goals(
    session: AsyncSession, project_id: str, org_id: str, goal_ids: list[str]
) -> None:
    await session.execute(
        delete(ProjectGoal).where(ProjectGoal.project_id == project_id)
    )
    for goal_id in goal_ids:
        session.add(ProjectGoal(project_id=project_id, goal_id=goal_id, org_id=org_id))
    await session.flush()
