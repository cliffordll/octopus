"""add agent configuration and runtime state tables

Revision ID: 20260527_000004
Revises: 20260527_000003
Create Date: 2026-05-27 00:00:04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_000004"
down_revision = "20260527_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_config_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("rolled_back_from_revision_id", sa.String(length=36), nullable=True),
        sa.Column("changed_keys", sa.JSON(), nullable=False),
        sa.Column("before_config", sa.JSON(), nullable=False),
        sa.Column("after_config", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "agent_config_revisions_company_agent_created_idx",
        "agent_config_revisions",
        ["org_id", "agent_id", "created_at"],
    )
    op.create_index(
        "agent_config_revisions_agent_created_idx",
        "agent_config_revisions",
        ["agent_id", "created_at"],
    )

    op.create_table(
        "agent_runtime_state",
        sa.Column(
            "agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("agent_runtime_type", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("last_run_id", sa.String(length=36), nullable=True),
        sa.Column("last_run_status", sa.Text(), nullable=True),
        sa.Column("total_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_cached_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("total_cost_cents", sa.BigInteger(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        "agent_runtime_state_company_agent_idx",
        "agent_runtime_state",
        ["org_id", "agent_id"],
    )
    op.create_index(
        "agent_runtime_state_company_updated_idx",
        "agent_runtime_state",
        ["org_id", "updated_at"],
    )

    op.create_table(
        "agent_task_sessions",
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
        sa.Column("agent_runtime_type", sa.Text(), nullable=False),
        sa.Column("task_key", sa.Text(), nullable=False),
        sa.Column("session_params_json", sa.JSON(), nullable=True),
        sa.Column("session_display_id", sa.Text(), nullable=True),
        sa.Column("last_run_id", sa.String(length=36), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        "agent_task_sessions_company_agent_adapter_task_uniq",
        "agent_task_sessions",
        ["org_id", "agent_id", "agent_runtime_type", "task_key"],
        unique=True,
    )
    op.create_index(
        "agent_task_sessions_company_agent_updated_idx",
        "agent_task_sessions",
        ["org_id", "agent_id", "updated_at"],
    )
    op.create_index(
        "agent_task_sessions_company_task_updated_idx",
        "agent_task_sessions",
        ["org_id", "task_key", "updated_at"],
    )

    op.create_table(
        "agent_wakeup_requests",
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
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("trigger_detail", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("coalesced_count", sa.Integer(), nullable=False),
        sa.Column("requested_by_actor_type", sa.Text(), nullable=True),
        sa.Column("requested_by_actor_id", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
        "agent_wakeup_requests_company_agent_status_idx",
        "agent_wakeup_requests",
        ["org_id", "agent_id", "status"],
    )
    op.create_index(
        "agent_wakeup_requests_company_requested_idx",
        "agent_wakeup_requests",
        ["org_id", "requested_at"],
    )
    op.create_index(
        "agent_wakeup_requests_agent_requested_idx",
        "agent_wakeup_requests",
        ["agent_id", "requested_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "agent_wakeup_requests_agent_requested_idx", table_name="agent_wakeup_requests"
    )
    op.drop_index(
        "agent_wakeup_requests_company_requested_idx",
        table_name="agent_wakeup_requests",
    )
    op.drop_index(
        "agent_wakeup_requests_company_agent_status_idx",
        table_name="agent_wakeup_requests",
    )
    op.drop_table("agent_wakeup_requests")
    op.drop_index(
        "agent_task_sessions_company_task_updated_idx", table_name="agent_task_sessions"
    )
    op.drop_index(
        "agent_task_sessions_company_agent_updated_idx",
        table_name="agent_task_sessions",
    )
    op.drop_index(
        "agent_task_sessions_company_agent_adapter_task_uniq",
        table_name="agent_task_sessions",
    )
    op.drop_table("agent_task_sessions")
    op.drop_index(
        "agent_runtime_state_company_updated_idx", table_name="agent_runtime_state"
    )
    op.drop_index(
        "agent_runtime_state_company_agent_idx", table_name="agent_runtime_state"
    )
    op.drop_table("agent_runtime_state")
    op.drop_index(
        "agent_config_revisions_agent_created_idx", table_name="agent_config_revisions"
    )
    op.drop_index(
        "agent_config_revisions_company_agent_created_idx",
        table_name="agent_config_revisions",
    )
    op.drop_table("agent_config_revisions")
