from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (Index("goals_company_idx", "org_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str] = mapped_column(Text, nullable=False, default="task")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="planned")
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("goals.id"), nullable=True
    )
    owner_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectGoal(Base):
    __tablename__ = "project_goals"
    __table_args__ = (
        Index("project_goals_project_idx", "project_id"),
        Index("project_goals_goal_idx", "goal_id"),
        Index("project_goals_company_idx", "org_id"),
    )

    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goals.id", ondelete="CASCADE"), primary_key=True
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
