from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import IssueComment


async def insert_issue_comment(
    session: AsyncSession, fields: Mapping[str, Any]
) -> IssueComment:
    values = dict(fields)
    now = datetime.now(UTC)
    if "created_at" not in values:
        latest_created_at = await session.scalar(
            select(IssueComment.created_at)
            .where(IssueComment.issue_id == values["issue_id"])
            .order_by(IssueComment.created_at.desc())
            .limit(1)
        )
        if latest_created_at is not None and latest_created_at.tzinfo is None:
            latest_created_at = latest_created_at.replace(tzinfo=UTC)
        if latest_created_at is not None and now <= latest_created_at:
            now = latest_created_at + timedelta(microseconds=1)
    values.setdefault("created_at", now)
    values.setdefault("updated_at", now)
    row = IssueComment(**values)
    session.add(row)
    await session.flush()
    return row


async def get_issue_comment_by_request_id(
    session: AsyncSession,
    *,
    org_id: str,
    issue_id: str,
    request_id: str,
) -> IssueComment | None:
    return await session.scalar(
        select(IssueComment).where(
            IssueComment.org_id == org_id,
            IssueComment.issue_id == issue_id,
            IssueComment.request_id == request_id,
        )
    )


async def insert_issue_comment_idempotent(
    session: AsyncSession, fields: Mapping[str, Any]
) -> tuple[IssueComment, bool]:
    values = dict(fields)
    request_id = values.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        return await insert_issue_comment(session, values), True
    try:
        async with session.begin_nested():
            row = await insert_issue_comment(session, values)
        return row, True
    except IntegrityError:
        existing = await get_issue_comment_by_request_id(
            session,
            org_id=str(values["org_id"]),
            issue_id=str(values["issue_id"]),
            request_id=request_id,
        )
        if existing is None:
            raise
        return existing, False


async def list_issue_comments(
    session: AsyncSession, issue_id: str
) -> Sequence[IssueComment]:
    result = await session.execute(
        select(IssueComment)
        .where(IssueComment.issue_id == issue_id)
        .order_by(IssueComment.created_at, IssueComment.id)
    )
    return result.scalars().all()
