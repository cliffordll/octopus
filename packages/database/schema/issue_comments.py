from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class IssueComment(Base):
    __tablename__ = "issue_comments"
    __table_args__ = (
        Index("issue_comments_issue_idx", "issue_id"),
        Index("issue_comments_company_idx", "org_id"),
        Index(
            "issue_comments_company_issue_created_at_idx",
            "org_id",
            "issue_id",
            "created_at",
        ),
        Index(
            "issue_comments_company_author_issue_created_at_idx",
            "org_id",
            "author_user_id",
            "issue_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    issue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("issues.id"), nullable=False
    )
    author_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    author_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
