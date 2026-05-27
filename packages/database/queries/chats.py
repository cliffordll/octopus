from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import ChatConversation, ChatMessage


async def create_conversation(
    session: AsyncSession, fields: Mapping[str, Any]
) -> ChatConversation:
    row = ChatConversation(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def get_conversation(
    session: AsyncSession, conversation_id: str
) -> ChatConversation | None:
    return await session.get(ChatConversation, conversation_id)


async def list_conversations(
    session: AsyncSession, org_id: str
) -> Sequence[ChatConversation]:
    result = await session.execute(
        select(ChatConversation)
        .where(ChatConversation.org_id == org_id)
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.id.desc())
    )
    return result.scalars().all()


async def create_message(
    session: AsyncSession, fields: Mapping[str, Any]
) -> ChatMessage:
    row = ChatMessage(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def list_messages(
    session: AsyncSession, conversation_id: str
) -> Sequence[ChatMessage]:
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
    )
    return result.scalars().all()


async def touch_conversation(
    session: AsyncSession, conversation_id: str, at: datetime
) -> ChatConversation | None:
    result = await session.execute(
        update(ChatConversation)
        .where(ChatConversation.id == conversation_id)
        .values(last_message_at=at, updated_at=datetime.now(UTC))
        .returning(ChatConversation)
    )
    return result.scalar_one_or_none()
