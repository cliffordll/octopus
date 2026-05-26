from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Issue


async def list_org_issues(
    session: AsyncSession,
    org_id: str,
    *,
    status: str | None = None,
    assignee_agent_id: str | None = None,
) -> Sequence[Issue]:
    stmt = select(Issue).where(Issue.org_id == org_id)
    if status is not None:
        stmt = stmt.where(Issue.status == status)
    if assignee_agent_id is not None:
        stmt = stmt.where(Issue.assignee_agent_id == assignee_agent_id)
    stmt = stmt.order_by(Issue.board_order, Issue.created_at)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_issue_by_id(session: AsyncSession, issue_id: str) -> Issue | None:
    result = await session.execute(select(Issue).where(Issue.id == issue_id))
    return result.scalar_one_or_none()
