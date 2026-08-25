from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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


class HeartbeatRun(Base):
    __tablename__ = "heartbeat_runs"
    __table_args__ = (
        Index(
            "heartbeat_runs_company_agent_started_idx",
            "org_id",
            "agent_id",
            "started_at",
        ),
        Index(
            "heartbeat_runs_status_execution_lease_created_idx",
            "status",
            "execution_lease_expires_at",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=False
    )
    invocation_source: Mapped[str] = mapped_column(
        Text, nullable=False, default="on_demand"
    )
    run_purpose: Mapped[str] = mapped_column(
        Text, nullable=False, default="task_execution"
    )
    trigger_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    wakeup_request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_wakeup_requests.id")
    )
    exit_code: Mapped[int | None] = mapped_column(Integer)
    signal: Mapped[str | None] = mapped_column(Text)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    session_id_before: Mapped[str | None] = mapped_column(Text)
    session_id_after: Mapped[str | None] = mapped_column(Text)
    log_store: Mapped[str | None] = mapped_column(Text)
    log_ref: Mapped[str | None] = mapped_column(Text)
    log_bytes: Mapped[int | None] = mapped_column(BigInteger)
    log_sha256: Mapped[str | None] = mapped_column(Text)
    log_compressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stdout_excerpt: Mapped[str | None] = mapped_column(Text)
    stderr_excerpt: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    external_run_id: Mapped[str | None] = mapped_column(Text)
    process_pid: Mapped[int | None] = mapped_column(Integer)
    process_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    process_exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    yield_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_owner_token: Mapped[str | None] = mapped_column(Text)
    execution_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    terminal_effects_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    terminal_effects_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    terminal_effects_completed_json: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    terminal_effects_dead_lettered_json: Mapped[list[str] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    terminal_effects_attempts_json: Mapped[dict[str, int] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    terminal_effects_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    terminal_effects_dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    terminal_effects_claim_token: Mapped[str | None] = mapped_column(Text)
    terminal_effects_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    terminal_effects_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    terminal_effects_last_error: Mapped[str | None] = mapped_column(Text)
    retry_of_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("heartbeat_runs.id", ondelete="SET NULL")
    )
    process_loss_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HeartbeatRunEvent(Base):
    __tablename__ = "heartbeat_run_events"
    __table_args__ = (
        Index("heartbeat_run_events_run_seq_idx", "run_id", "seq"),
        Index("heartbeat_run_events_company_run_idx", "org_id", "run_id"),
        Index("heartbeat_run_events_company_created_idx", "org_id", "created_at"),
        Index(
            "heartbeat_run_events_run_idempotency_key_uq",
            "run_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key is not null"),
            sqlite_where=text("idempotency_key is not null"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("heartbeat_runs.id"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    stream: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
