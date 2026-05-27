"""add heartbeat execution tables

Revision ID: 20260527_000005
Revises: 20260527_000004
Create Date: 2026-05-27 00:00:05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_000005"
down_revision = "20260527_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "heartbeat_runs",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "agent_id", sa.String(length=36), sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("invocation_source", sa.Text(), nullable=False),
        sa.Column("trigger_detail", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "wakeup_request_id",
            sa.String(length=36),
            sa.ForeignKey("agent_wakeup_requests.id"),
            nullable=True,
        ),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("signal", sa.Text(), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("session_id_before", sa.Text(), nullable=True),
        sa.Column("session_id_after", sa.Text(), nullable=True),
        sa.Column("log_store", sa.Text(), nullable=True),
        sa.Column("log_ref", sa.Text(), nullable=True),
        sa.Column("log_bytes", sa.BigInteger(), nullable=True),
        sa.Column("log_sha256", sa.Text(), nullable=True),
        sa.Column("log_compressed", sa.Boolean(), nullable=False),
        sa.Column("stdout_excerpt", sa.Text(), nullable=True),
        sa.Column("stderr_excerpt", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("external_run_id", sa.Text(), nullable=True),
        sa.Column("process_pid", sa.Integer(), nullable=True),
        sa.Column("process_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "retry_of_run_id",
            sa.String(length=36),
            sa.ForeignKey("heartbeat_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("process_loss_retry_count", sa.Integer(), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "heartbeat_runs_company_agent_started_idx",
        "heartbeat_runs",
        ["org_id", "agent_id", "started_at"],
    )
    op.create_table(
        "heartbeat_run_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("heartbeat_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "agent_id", sa.String(length=36), sa.ForeignKey("agents.id"), nullable=False
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("stream", sa.Text(), nullable=True),
        sa.Column("level", sa.Text(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "heartbeat_run_events_run_seq_idx", "heartbeat_run_events", ["run_id", "seq"]
    )
    op.create_index(
        "heartbeat_run_events_company_run_idx",
        "heartbeat_run_events",
        ["org_id", "run_id"],
    )
    op.create_index(
        "heartbeat_run_events_company_created_idx",
        "heartbeat_run_events",
        ["org_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "heartbeat_run_events_company_created_idx", table_name="heartbeat_run_events"
    )
    op.drop_index(
        "heartbeat_run_events_company_run_idx", table_name="heartbeat_run_events"
    )
    op.drop_index("heartbeat_run_events_run_seq_idx", table_name="heartbeat_run_events")
    op.drop_table("heartbeat_run_events")
    op.drop_index(
        "heartbeat_runs_company_agent_started_idx", table_name="heartbeat_runs"
    )
    op.drop_table("heartbeat_runs")
