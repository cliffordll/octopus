from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Organization


async def list_organizations(session: AsyncSession) -> Sequence[Organization]:
    result = await session.execute(
        select(Organization).order_by(Organization.created_at)
    )
    return result.scalars().all()


async def get_organization_by_id(
    session: AsyncSession, organization_id: str
) -> Organization | None:
    result = await session.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    return result.scalar_one_or_none()


async def update_organization(
    session: AsyncSession,
    organization_id: str,
    fields: Mapping[str, Any],
) -> Organization | None:
    if not fields:
        return await get_organization_by_id(session, organization_id)

    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)

    result = await session.execute(
        update(Organization)
        .where(Organization.id == organization_id)
        .values(**values)
        .returning(Organization)
    )
    return result.scalar_one_or_none()
