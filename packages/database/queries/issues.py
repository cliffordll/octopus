from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Issue, IssueApproval


async def create_issue(session: AsyncSession, fields: Mapping[str, Any]) -> Issue:
    row = Issue(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def list_org_issues(
    session: AsyncSession,
    org_id: str,
    *,
    status: str | None = None,
    assignee_agent_id: str | None = None,
    project_id: str | None = None,
    goal_id: str | None = None,
    parent_id: str | None = None,
    origin_kind: str | None = None,
    origin_id: str | None = None,
) -> Sequence[Issue]:
    stmt = select(Issue).where(Issue.org_id == org_id)
    if status is not None:
        stmt = stmt.where(Issue.status == status)
    if assignee_agent_id is not None:
        stmt = stmt.where(Issue.assignee_agent_id == assignee_agent_id)
    if project_id is not None:
        stmt = stmt.where(Issue.project_id == project_id)
    if goal_id is not None:
        stmt = stmt.where(Issue.goal_id == goal_id)
    if parent_id is not None:
        stmt = stmt.where(Issue.parent_id == parent_id)
    if origin_kind is not None:
        stmt = stmt.where(Issue.origin_kind == origin_kind)
    if origin_id is not None:
        stmt = stmt.where(Issue.origin_id == origin_id)
    stmt = stmt.order_by(Issue.board_order, Issue.created_at)
    result = await session.execute(stmt)
    return result.scalars().all()


async def list_agent_inbox_issues(
    session: AsyncSession, org_id: str, agent_id: str
) -> Sequence[Issue]:
    relationship_rank = case(
        (Issue.reviewer_agent_id == agent_id, 0),
        (Issue.status == "in_progress", 1),
        (Issue.status == "todo", 2),
        else_=3,
    )
    priority_rank = case(
        (Issue.priority == "critical", 0),
        (Issue.priority == "high", 1),
        (Issue.priority == "medium", 2),
        else_=3,
    )
    result = await session.execute(
        select(Issue)
        .where(
            Issue.org_id == org_id,
            Issue.hidden_at.is_(None),
            or_(
                (
                    (Issue.reviewer_agent_id == agent_id)
                    & Issue.status.in_(("in_review", "blocked"))
                ),
                (
                    (Issue.assignee_agent_id == agent_id)
                    & Issue.status.in_(("todo", "in_progress", "blocked"))
                ),
            ),
        )
        .order_by(relationship_rank, priority_rank, Issue.updated_at.desc(), Issue.id)
    )
    return result.scalars().all()


async def get_issue_by_id(session: AsyncSession, issue_id: str) -> Issue | None:
    result = await session.execute(
        select(Issue).where(or_(Issue.id == issue_id, Issue.identifier == issue_id))
    )
    return result.scalar_one_or_none()


async def update_issue(
    session: AsyncSession,
    issue_id: str,
    fields: Mapping[str, Any],
) -> Issue | None:
    if not fields:
        return await get_issue_by_id(session, issue_id)

    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)

    result = await session.execute(
        update(Issue)
        .where(or_(Issue.id == issue_id, Issue.identifier == issue_id))
        .values(**values)
        .returning(Issue)
    )
    return result.scalar_one_or_none()


async def recover_blocked_linked_issues_for_approval(
    session: AsyncSession,
    approval_id: str,
) -> Sequence[Issue]:
    result = await session.execute(
        select(Issue)
        .join(IssueApproval, IssueApproval.issue_id == Issue.id)
        .where(IssueApproval.approval_id == approval_id, Issue.status == "blocked")
        .order_by(Issue.created_at)
    )
    rows = result.scalars().all()
    now = datetime.now(UTC)
    for row in rows:
        has_assignee = (
            row.assignee_agent_id is not None or row.assignee_user_id is not None
        )
        row.status = "in_progress" if has_assignee else "todo"
        row.updated_at = now
    await session.flush()
    return rows
