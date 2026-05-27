from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("projects_company_idx", "org_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    goal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="backlog")
    lead_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_workspace_policy: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
