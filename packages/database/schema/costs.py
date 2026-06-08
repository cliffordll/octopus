from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class CostEvent(Base):
    __tablename__ = "cost_events"
    __table_args__ = (
        Index("cost_events_org_occurred_idx", "org_id", "occurred_at"),
        Index(
            "cost_events_org_agent_occurred_idx", "org_id", "agent_id", "occurred_at"
        ),
        Index(
            "cost_events_org_project_occurred_idx",
            "org_id",
            "project_id",
            "occurred_at",
        ),
        Index("cost_events_org_provider_idx", "org_id", "provider"),
        Index("cost_events_org_biller_idx", "org_id", "biller"),
        Index("cost_events_org_source_idx", "org_id", "source_type", "source_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=True
    )
    source_type: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)
    runtime_type: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    biller: Mapped[str | None] = mapped_column(Text)
    cost_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON().with_variant(JSONB(), "postgresql")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
