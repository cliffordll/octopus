from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Approval


async def list_org_approvals(
    session: AsyncSession,
    org_id: str,
    *,
    status: str | None = None,
) -> Sequence[Approval]:
    stmt = select(Approval).where(Approval.org_id == org_id)
    if status is not None:
        stmt = stmt.where(Approval.status == status)
    stmt = stmt.order_by(Approval.created_at)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_approval_by_id(
    session: AsyncSession, approval_id: str
) -> Approval | None:
    result = await session.execute(select(Approval).where(Approval.id == approval_id))
    return result.scalar_one_or_none()
