from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import OrganizationResource, ProjectResourceAttachment


async def get_organization_resource_by_id(
    session: AsyncSession, resource_id: str
) -> OrganizationResource | None:
    result = await session.execute(
        select(OrganizationResource).where(OrganizationResource.id == resource_id)
    )
    return result.scalar_one_or_none()


async def create_organization_resource(
    session: AsyncSession, fields: Mapping[str, Any]
) -> OrganizationResource:
    row = OrganizationResource(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def list_project_resource_attachments(
    session: AsyncSession, project_id: str
) -> Sequence[ProjectResourceAttachment]:
    result = await session.execute(
        select(ProjectResourceAttachment)
        .where(ProjectResourceAttachment.project_id == project_id)
        .order_by(
            ProjectResourceAttachment.sort_order,
            ProjectResourceAttachment.created_at,
        )
    )
    return result.scalars().all()


async def get_project_resource_attachment(
    session: AsyncSession, project_id: str, attachment_id: str
) -> ProjectResourceAttachment | None:
    result = await session.execute(
        select(ProjectResourceAttachment).where(
            ProjectResourceAttachment.project_id == project_id,
            ProjectResourceAttachment.id == attachment_id,
        )
    )
    return result.scalar_one_or_none()


async def get_project_resource_attachment_by_resource(
    session: AsyncSession, project_id: str, resource_id: str
) -> ProjectResourceAttachment | None:
    result = await session.execute(
        select(ProjectResourceAttachment).where(
            ProjectResourceAttachment.project_id == project_id,
            ProjectResourceAttachment.resource_id == resource_id,
        )
    )
    return result.scalar_one_or_none()


async def create_project_resource_attachment(
    session: AsyncSession, fields: Mapping[str, Any]
) -> ProjectResourceAttachment:
    row = ProjectResourceAttachment(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_project_resource_attachment(
    session: AsyncSession,
    attachment_id: str,
    fields: Mapping[str, Any],
) -> ProjectResourceAttachment | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(ProjectResourceAttachment)
        .where(ProjectResourceAttachment.id == attachment_id)
        .values(**values)
        .returning(ProjectResourceAttachment)
    )
    return result.scalar_one_or_none()


async def delete_project_resource_attachment(
    session: AsyncSession, attachment_id: str
) -> ProjectResourceAttachment | None:
    result = await session.execute(
        delete(ProjectResourceAttachment)
        .where(ProjectResourceAttachment.id == attachment_id)
        .returning(ProjectResourceAttachment)
    )
    return result.scalar_one_or_none()


async def delete_project_resource_attachments(
    session: AsyncSession, project_id: str
) -> None:
    await session.execute(
        delete(ProjectResourceAttachment).where(
            ProjectResourceAttachment.project_id == project_id
        )
    )
