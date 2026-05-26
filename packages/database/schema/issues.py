from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        Index("issues_company_status_idx", "org_id", "status"),
        Index(
            "issues_company_status_board_order_idx",
            "org_id",
            "status",
            "board_order",
        ),
        Index("issues_identifier_idx", "identifier", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    project_workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    goal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("issues.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="backlog")
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    board_order: Mapped[int] = mapped_column(nullable=False, default=0)
    assignee_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    assignee_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewer_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewer_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    checkout_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_agent_name_key: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    execution_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    issue_number: Mapped[int | None] = mapped_column(nullable=True)
    identifier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual"
    )
    origin_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origin_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_depth: Mapped[int] = mapped_column(nullable=False, default=0)
    billing_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assignee_agent_runtime_overrides: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    execution_workspace_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    execution_workspace_preference: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    execution_workspace_settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
