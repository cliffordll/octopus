from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class ApprovalComment(Base):
    __tablename__ = "approval_comments"
    __table_args__ = (
        Index("approval_comments_company_idx", "org_id"),
        Index("approval_comments_approval_idx", "approval_id"),
        Index(
            "approval_comments_approval_created_idx",
            "approval_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    approval_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approvals.id"), nullable=False
    )
    author_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    author_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
