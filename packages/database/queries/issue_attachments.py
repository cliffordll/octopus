from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Asset, ChatAttachment, IssueAttachment


async def create_issue_attachment(
    session: AsyncSession,
    *,
    asset_fields: Mapping[str, Any],
    attachment_fields: Mapping[str, Any],
) -> tuple[IssueAttachment, Asset]:
    asset = Asset(**dict(asset_fields))
    session.add(asset)
    await session.flush()
    attachment = IssueAttachment(**{**dict(attachment_fields), "asset_id": asset.id})
    session.add(attachment)
    await session.flush()
    return attachment, asset


async def list_issue_attachments(
    session: AsyncSession, issue_id: str
) -> Sequence[tuple[IssueAttachment, Asset]]:
    result = await session.execute(
        select(IssueAttachment, Asset)
        .join(Asset, IssueAttachment.asset_id == Asset.id)
        .where(IssueAttachment.issue_id == issue_id)
        .order_by(IssueAttachment.created_at, IssueAttachment.id)
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_issue_attachment(
    session: AsyncSession, attachment_id: str
) -> tuple[IssueAttachment, Asset] | None:
    result = await session.execute(
        select(IssueAttachment, Asset)
        .join(Asset, IssueAttachment.asset_id == Asset.id)
        .where(IssueAttachment.id == attachment_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return row[0], row[1]


async def delete_issue_attachment(
    session: AsyncSession, attachment_id: str
) -> tuple[IssueAttachment, Asset, bool] | None:
    current = await get_issue_attachment(session, attachment_id)
    if current is None:
        return None
    attachment, asset = current
    await session.delete(attachment)
    await session.flush()
    remaining_issue_refs = await session.scalar(
        select(func.count())
        .select_from(IssueAttachment)
        .where(IssueAttachment.asset_id == asset.id)
    )
    remaining_chat_refs = await session.scalar(
        select(func.count())
        .select_from(ChatAttachment)
        .where(ChatAttachment.asset_id == asset.id)
    )
    should_delete_asset = not remaining_issue_refs and not remaining_chat_refs
    if should_delete_asset:
        await session.execute(delete(Asset).where(Asset.id == asset.id))
    return attachment, asset, should_delete_asset
