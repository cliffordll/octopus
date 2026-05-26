from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import OrganizationOwnership


async def get_ownership_by_org_id(
    session: AsyncSession, organization_id: str
) -> OrganizationOwnership | None:
    result = await session.execute(
        select(OrganizationOwnership).where(
            OrganizationOwnership.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def list_ownerships_for_pod(
    session: AsyncSession, pod_id: str
) -> Sequence[OrganizationOwnership]:
    result = await session.execute(
        select(OrganizationOwnership)
        .where(OrganizationOwnership.pod_id == pod_id)
        .order_by(OrganizationOwnership.organization_id)
    )
    return result.scalars().all()
