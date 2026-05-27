from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class AgentConfigRevision(Base):
    __tablename__ = "agent_config_revisions"
    __table_args__ = (
        Index(
            "agent_config_revisions_company_agent_created_idx",
            "org_id",
            "agent_id",
            "created_at",
        ),
        Index("agent_config_revisions_agent_created_idx", "agent_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    created_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="patch")
    rolled_back_from_revision_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    changed_keys: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    before_config: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    after_config: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentRuntimeState(Base):
    __tablename__ = "agent_runtime_state"
    __table_args__ = (
        Index("agent_runtime_state_company_agent_idx", "org_id", "agent_id"),
        Index("agent_runtime_state_company_updated_idx", "org_id", "updated_at"),
    )

    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id"), primary_key=True
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    agent_runtime_type: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_input_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    total_output_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    total_cached_input_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    total_cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentTaskSession(Base):
    __tablename__ = "agent_task_sessions"
    __table_args__ = (
        Index(
            "agent_task_sessions_company_agent_adapter_task_uniq",
            "org_id",
            "agent_id",
            "agent_runtime_type",
            "task_key",
            unique=True,
        ),
        Index(
            "agent_task_sessions_company_agent_updated_idx",
            "org_id",
            "agent_id",
            "updated_at",
        ),
        Index(
            "agent_task_sessions_company_task_updated_idx",
            "org_id",
            "task_key",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=False
    )
    agent_runtime_type: Mapped[str] = mapped_column(Text, nullable=False)
    task_key: Mapped[str] = mapped_column(Text, nullable=False)
    session_params_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    session_display_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentWakeupRequest(Base):
    __tablename__ = "agent_wakeup_requests"
    __table_args__ = (
        Index(
            "agent_wakeup_requests_company_agent_status_idx",
            "org_id",
            "agent_id",
            "status",
        ),
        Index("agent_wakeup_requests_company_requested_idx", "org_id", "requested_at"),
        Index("agent_wakeup_requests_agent_requested_idx", "agent_id", "requested_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    coalesced_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_by_actor_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_actor_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
