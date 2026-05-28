from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ._base import Base, new_uuid


class AgentEnabledSkill(Base):
    __tablename__ = "agent_enabled_skills"
    __table_args__ = (
        Index("agent_enabled_skills_agent_idx", "agent_id"),
        Index("agent_enabled_skills_org_idx", "org_id"),
        Index(
            "agent_enabled_skills_agent_skill_idx", "agent_id", "skill_key", unique=True
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    skill_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
