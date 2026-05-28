from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import ProjectWorkspace


async def list_project_workspaces(
    session: AsyncSession, project_id: str
) -> Sequence[ProjectWorkspace]:
    result = await session.execute(
        select(ProjectWorkspace)
        .where(ProjectWorkspace.project_id == project_id)
        .order_by(
            desc(ProjectWorkspace.is_primary),
            ProjectWorkspace.created_at,
            ProjectWorkspace.id,
        )
    )
    return result.scalars().all()


async def create_project_workspace(
    session: AsyncSession, fields: Mapping[str, Any]
) -> ProjectWorkspace:
    row = ProjectWorkspace(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def clear_primary_project_workspace(
    session: AsyncSession, *, org_id: str, project_id: str
) -> None:
    await session.execute(
        update(ProjectWorkspace)
        .where(
            ProjectWorkspace.org_id == org_id,
            ProjectWorkspace.project_id == project_id,
        )
        .values(is_primary=False, updated_at=datetime.now(UTC))
    )

