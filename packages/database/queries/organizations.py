from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Organization


async def list_organizations(session: AsyncSession) -> Sequence[Organization]:
    result = await session.execute(
        select(Organization).order_by(Organization.created_at)
    )
    return result.scalars().all()
