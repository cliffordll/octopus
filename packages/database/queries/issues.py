from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Issue


async def list_org_issues(session: AsyncSession, org_id: str) -> Sequence[Issue]:
    result = await session.execute(
        select(Issue)
        .where(Issue.org_id == org_id)
        .order_by(Issue.board_order, Issue.created_at)
    )
    return result.scalars().all()
