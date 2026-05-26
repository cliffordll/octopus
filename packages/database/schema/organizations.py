from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        Index("organizations_url_key_idx", "url_key", unique=True),
        Index("organizations_issue_prefix_idx", "issue_prefix", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    url_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    issue_prefix: Mapped[str] = mapped_column(Text, nullable=False, default="PAP")
    issue_counter: Mapped[int] = mapped_column(nullable=False, default=0)
    budget_monthly_cents: Mapped[int] = mapped_column(nullable=False, default=0)
    spent_monthly_cents: Mapped[int] = mapped_column(nullable=False, default=0)
    require_board_approval_for_new_agents: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    default_chat_issue_creation_mode: Mapped[str] = mapped_column(
        Text, nullable=False, default="manual_approval"
    )
    workspace_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    brand_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
