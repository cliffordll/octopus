from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import (
    Asset,
    ChatAttachment,
    ChatContextLink,
    ChatConversation,
    ChatConversationUserState,
    ChatMessage,
)
from ._compat import update_returning_one


async def create_conversation(
    session: AsyncSession, fields: Mapping[str, Any]
) -> ChatConversation:
    row = ChatConversation(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def create_context_link(
    session: AsyncSession, fields: Mapping[str, Any]
) -> ChatContextLink:
    existing = await get_context_link(
        session,
        conversation_id=str(fields["conversation_id"]),
        entity_type=str(fields["entity_type"]),
        entity_id=str(fields["entity_id"]),
    )
    if existing is not None:
        return existing
    row = ChatContextLink(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def get_context_link(
    session: AsyncSession,
    *,
    conversation_id: str,
    entity_type: str,
    entity_id: str,
) -> ChatContextLink | None:
    result = await session.execute(
        select(ChatContextLink).where(
            ChatContextLink.conversation_id == conversation_id,
            ChatContextLink.entity_type == entity_type,
            ChatContextLink.entity_id == entity_id,
        )
    )
    return result.scalar_one_or_none()


async def list_context_links(
    session: AsyncSession, conversation_ids: Sequence[str]
) -> Sequence[ChatContextLink]:
    if not conversation_ids:
        return []
    result = await session.execute(
        select(ChatContextLink)
        .where(ChatContextLink.conversation_id.in_(conversation_ids))
        .order_by(ChatContextLink.created_at, ChatContextLink.id)
    )
    return result.scalars().all()


async def delete_project_context_links(
    session: AsyncSession, *, org_id: str, conversation_id: str
) -> None:
    await session.execute(
        delete(ChatContextLink).where(
            ChatContextLink.org_id == org_id,
            ChatContextLink.conversation_id == conversation_id,
            ChatContextLink.entity_type == "project",
        )
    )


async def get_conversation(
    session: AsyncSession, conversation_id: str
) -> ChatConversation | None:
    return await session.get(ChatConversation, conversation_id)


async def list_conversations(
    session: AsyncSession,
    org_id: str,
    *,
    status: str = "active",
    q: str | None = None,
) -> Sequence[ChatConversation]:
    statement = select(ChatConversation).where(ChatConversation.org_id == org_id)
    if status != "all":
        statement = statement.where(ChatConversation.status == status)
    query = (q or "").strip().lower()
    if query:
        pattern = f"%{query}%"
        statement = statement.where(
            or_(
                func.lower(ChatConversation.title).like(pattern),
                func.lower(ChatConversation.summary).like(pattern),
            )
        )
    result = await session.execute(
        statement.order_by(
            ChatConversation.updated_at.desc(), ChatConversation.id.desc()
        )
    )
    return result.scalars().all()


async def update_conversation(
    session: AsyncSession, conversation_id: str, fields: Mapping[str, Any]
) -> ChatConversation | None:
    if not fields:
        return await get_conversation(session, conversation_id)
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        ChatConversation,
        ChatConversation.id == conversation_id,
        values,
    )


async def get_conversation_user_state(
    session: AsyncSession,
    *,
    org_id: str,
    conversation_id: str,
    user_id: str,
) -> ChatConversationUserState | None:
    result = await session.execute(
        select(ChatConversationUserState).where(
            ChatConversationUserState.org_id == org_id,
            ChatConversationUserState.conversation_id == conversation_id,
            ChatConversationUserState.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_conversation_user_state(
    session: AsyncSession,
    *,
    org_id: str,
    conversation_id: str,
    user_id: str,
    pinned: bool | None = None,
    unread: bool | None = None,
) -> ChatConversationUserState:
    now = datetime.now(UTC)
    row = await get_conversation_user_state(
        session, org_id=org_id, conversation_id=conversation_id, user_id=user_id
    )
    if row is None:
        row = ChatConversationUserState(
            org_id=org_id,
            conversation_id=conversation_id,
            user_id=user_id,
            last_read_at=now,
        )
        session.add(row)
    if pinned is not None:
        row.pinned_at = now if pinned else None
    if unread is not None:
        row.last_read_at = datetime.fromtimestamp(0, UTC) if unread else now
    row.updated_at = now
    await session.flush()
    return row


async def create_message(
    session: AsyncSession, fields: Mapping[str, Any]
) -> ChatMessage:
    row = ChatMessage(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def create_chat_attachment(
    session: AsyncSession,
    *,
    asset_fields: Mapping[str, Any],
    attachment_fields: Mapping[str, Any],
) -> tuple[Asset, ChatAttachment]:
    asset = Asset(**dict(asset_fields))
    session.add(asset)
    await session.flush()
    attachment = ChatAttachment(**{**dict(attachment_fields), "asset_id": asset.id})
    session.add(attachment)
    await session.flush()
    return asset, attachment


async def list_attachments_for_messages(
    session: AsyncSession, message_ids: Sequence[str]
) -> Sequence[tuple[ChatAttachment, Asset]]:
    if not message_ids:
        return []
    result = await session.execute(
        select(ChatAttachment, Asset)
        .join(Asset, ChatAttachment.asset_id == Asset.id)
        .where(ChatAttachment.message_id.in_(message_ids))
        .order_by(ChatAttachment.created_at, ChatAttachment.id)
    )
    return [(row[0], row[1]) for row in result.all()]


async def list_messages(
    session: AsyncSession, conversation_id: str
) -> Sequence[ChatMessage]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
    )
    return result.scalars().all()


async def get_latest_incoming_message_preview(
    session: AsyncSession, conversation_id: str
) -> str | None:
    """Return the most recent non-user message body for preview.

    Mirrors upstream ``listLatestReplyPreviews`` filter
    (``services/chats.helpers.ts:84``): role != 'user' and trimmed body
    non-empty, ordered by ``created_at`` desc.
    """

    result = await session.execute(
        select(ChatMessage.body)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role != "user",
            ChatMessage.superseded_at.is_(None),
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    body = result.scalar_one_or_none()
    if body is None:
        return None
    trimmed = body.strip()
    return trimmed or None


async def get_message(
    session: AsyncSession, *, conversation_id: str, message_id: str
) -> ChatMessage | None:
    result = await session.execute(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.id == message_id,
        )
    )
    return result.scalar_one_or_none()


async def get_message_by_approval_id(
    session: AsyncSession, approval_id: str
) -> ChatMessage | None:
    result = await session.execute(
        select(ChatMessage).where(ChatMessage.approval_id == approval_id)
    )
    return result.scalar_one_or_none()


async def update_message(
    session: AsyncSession,
    *,
    conversation_id: str,
    message_id: str,
    fields: Mapping[str, Any],
) -> ChatMessage | None:
    if not fields:
        return await get_message(
            session, conversation_id=conversation_id, message_id=message_id
        )
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        ChatMessage,
        (ChatMessage.conversation_id == conversation_id)
        & (ChatMessage.id == message_id),
        values,
    )


async def supersede_turn_messages(
    session: AsyncSession,
    *,
    conversation_id: str,
    chat_turn_id: str,
    at: datetime,
) -> None:
    await session.execute(
        update(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.chat_turn_id == chat_turn_id,
            ChatMessage.superseded_at.is_(None),
        )
        .values(superseded_at=at, updated_at=at)
    )


async def touch_conversation(
    session: AsyncSession, conversation_id: str, at: datetime
) -> ChatConversation | None:
    return await update_returning_one(
        session,
        ChatConversation,
        ChatConversation.id == conversation_id,
        {"last_message_at": at, "updated_at": datetime.now(UTC)},
    )
