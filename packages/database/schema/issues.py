from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


_OPEN_AUTOMATION_EXECUTION_WHERE = text(
    "origin_kind = 'automation_execution' "
    "and origin_id is not null "
    "and hidden_at is null "
    "and execution_run_id is not null "
    "and status in ('backlog', 'todo', 'in_progress', 'in_review', 'blocked')"
)


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
        Index(
            "issues_company_assignee_status_idx",
            "org_id",
            "assignee_agent_id",
            "status",
        ),
        Index(
            "issues_company_assignee_user_status_idx",
            "org_id",
            "assignee_user_id",
            "status",
        ),
        Index(
            "issues_company_reviewer_agent_status_idx",
            "org_id",
            "reviewer_agent_id",
            "status",
        ),
        Index(
            "issues_company_reviewer_user_status_idx",
            "org_id",
            "reviewer_user_id",
            "status",
        ),
        Index("issues_company_parent_idx", "org_id", "parent_id"),
        Index("issues_company_project_idx", "org_id", "project_id"),
        Index("issues_company_origin_idx", "org_id", "origin_kind", "origin_id"),
        Index(
            "issues_company_project_workspace_idx",
            "org_id",
            "project_workspace_id",
        ),
        Index(
            "issues_company_execution_workspace_idx",
            "org_id",
            "execution_workspace_id",
        ),
        Index("issues_identifier_idx", "identifier", unique=True),
        Index(
            "issues_open_automation_execution_uq",
            "org_id",
            "origin_kind",
            "origin_id",
            unique=True,
            postgresql_where=_OPEN_AUTOMATION_EXECUTION_WHERE,
            sqlite_where=_OPEN_AUTOMATION_EXECUTION_WHERE,
        ),
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
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="backlog")
    priority: Mapped[str] = mapped_column(Text, nullable=False, default="medium")
    board_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assignee_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    assignee_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewer_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    checkout_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_agent_name_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_kind: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    origin_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    billing_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_agent_runtime_overrides: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    execution_workspace_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    execution_workspace_preference: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    execution_workspace_settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
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
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IssueAttachment(Base):
    __tablename__ = "issue_attachments"
    __table_args__ = (
        Index("issue_attachments_company_issue_idx", "org_id", "issue_id"),
        Index("issue_attachments_comment_idx", "issue_comment_id"),
        Index("issue_attachments_asset_idx", "asset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    issue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    issue_comment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("issue_comments.id", ondelete="CASCADE")
    )
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    usage: Mapped[str] = mapped_column(Text, nullable=False, default="attachment")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
