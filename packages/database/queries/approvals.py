from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Approval


async def list_org_approvals(session: AsyncSession, org_id: str) -> Sequence[Approval]:
    result = await session.execute(
        select(Approval).where(Approval.org_id == org_id).order_by(Approval.created_at)
    )
    return result.scalars().all()
