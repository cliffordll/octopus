from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        Index("chat_conversations_org_updated_idx", "org_id", "updated_at"),
        Index(
            "chat_conversations_org_status_updated_idx",
            "org_id",
            "status",
            "updated_at",
        ),
        Index("chat_conversations_primary_issue_idx", "primary_issue_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New chat")
    summary: Mapped[str | None] = mapped_column(Text)
    preferred_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL")
    )
    routed_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL")
    )
    primary_issue_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("issues.id", ondelete="SET NULL")
    )
    issue_creation_mode: Mapped[str] = mapped_column(
        Text, nullable=False, default="manual_approval"
    )
    plan_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[str | None] = mapped_column(Text)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index(
            "chat_messages_conversation_created_idx", "conversation_id", "created_at"
        ),
        Index(
            "chat_messages_org_conversation_created_idx",
            "org_id",
            "conversation_id",
            "created_at",
        ),
        Index("chat_messages_approval_idx", "approval_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="message")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="completed")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    structured_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    approval_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("approvals.id", ondelete="SET NULL")
    )
    replying_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL")
    )
    chat_turn_id: Mapped[str | None] = mapped_column(String(36))
    turn_variant: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("assets_company_created_idx", "org_id", "created_at"),
        Index("assets_company_provider_idx", "org_id", "provider"),
        UniqueConstraint("org_id", "object_key", name="assets_company_object_key_uq"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(Text)
    created_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id")
    )
    created_by_user_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChatAttachment(Base):
    __tablename__ = "chat_attachments"
    __table_args__ = (
        Index(
            "chat_attachments_conversation_message_idx",
            "conversation_id",
            "message_id",
        ),
        Index("chat_attachments_company_conversation_idx", "org_id", "conversation_id"),
        Index("chat_attachments_asset_idx", "asset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChatConversationUserState(Base):
    __tablename__ = "chat_conversation_user_states"
    __table_args__ = (
        Index(
            "chat_conversation_user_states_org_conversation_idx",
            "org_id",
            "conversation_id",
        ),
        Index("chat_conversation_user_states_org_user_idx", "org_id", "user_id"),
        UniqueConstraint(
            "org_id",
            "conversation_id",
            "user_id",
            name="chat_conversation_user_states_org_conversation_user_idx",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChatContextLink(Base):
    __tablename__ = "chat_context_links"
    __table_args__ = (
        Index(
            "chat_context_links_conversation_entity_idx",
            "conversation_id",
            "entity_type",
            "entity_id",
        ),
        Index(
            "chat_context_links_company_entity_idx",
            "org_id",
            "entity_type",
            "entity_id",
        ),
        UniqueConstraint(
            "conversation_id",
            "entity_type",
            "entity_id",
            name="chat_context_links_unique_conversation_entity_idx",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON().with_variant(JSONB(), "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
