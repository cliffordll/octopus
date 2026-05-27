from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Approval, IssueApproval


async def create_approval(session: AsyncSession, fields: Mapping[str, Any]) -> Approval:
    row = Approval(**dict(fields))
    session.add(row)
    await session.flush()
    return row


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


async def update_approval(
    session: AsyncSession,
    approval_id: str,
    fields: Mapping[str, Any],
) -> Approval | None:
    if not fields:
        return await get_approval_by_id(session, approval_id)

    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    if (
        "status" in values
        and values["status"] in {"approved", "rejected", "revision_requested"}
        and "decided_at" not in values
    ):
        values["decided_at"] = datetime.now(UTC)

    result = await session.execute(
        update(Approval)
        .where(Approval.id == approval_id)
        .values(**values)
        .returning(Approval)
    )
    return result.scalar_one_or_none()


async def link_issues_to_approval(
    session: AsyncSession,
    *,
    org_id: str,
    approval_id: str,
    issue_ids: Sequence[str],
    linked_by_agent_id: str | None = None,
    linked_by_user_id: str | None = None,
) -> list[IssueApproval]:
    rows = [
        IssueApproval(
            org_id=org_id,
            issue_id=issue_id,
            approval_id=approval_id,
            linked_by_agent_id=linked_by_agent_id,
            linked_by_user_id=linked_by_user_id,
        )
        for issue_id in issue_ids
    ]
    session.add_all(rows)
    await session.flush()
    return rows
