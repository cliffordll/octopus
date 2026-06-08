from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Project
from ._compat import delete_returning_one, update_returning_one


async def list_org_projects(session: AsyncSession, org_id: str) -> Sequence[Project]:
    result = await session.execute(
        select(Project).where(Project.org_id == org_id).order_by(Project.created_at)
    )
    return result.scalars().all()


async def get_project_by_id(session: AsyncSession, project_id: str) -> Project | None:
    result = await session.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def create_project(session: AsyncSession, fields: Mapping[str, Any]) -> Project:
    row = Project(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_project(
    session: AsyncSession,
    project_id: str,
    fields: Mapping[str, Any],
) -> Project | None:
    if not fields:
        return await get_project_by_id(session, project_id)
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session, Project, Project.id == project_id, values
    )


async def delete_project(session: AsyncSession, project_id: str) -> Project | None:
    return await delete_returning_one(session, Project, Project.id == project_id)
