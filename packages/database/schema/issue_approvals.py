from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, PrimaryKeyConstraint, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base


class IssueApproval(Base):
    __tablename__ = "issue_approvals"
    __table_args__ = (
        PrimaryKeyConstraint("issue_id", "approval_id", name="issue_approvals_pk"),
    )

    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    issue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("issues.id"), nullable=False
    )
    approval_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approvals.id"), nullable=False
    )
    linked_by_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    linked_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
