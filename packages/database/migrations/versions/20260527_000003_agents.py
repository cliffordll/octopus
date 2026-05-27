"""add agent management table

Revision ID: 20260527_000003
Revises: 20260527_000002
Create Date: 2026-05-27 00:00:03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_000003"
down_revision = "20260527_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("workspace_key", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "reports_to",
            sa.String(length=36),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        sa.Column("capabilities", sa.Text(), nullable=True),
        sa.Column("agent_runtime_type", sa.Text(), nullable=False),
        sa.Column("agent_runtime_config", sa.JSON(), nullable=False),
        sa.Column("runtime_config", sa.JSON(), nullable=False),
        sa.Column("budget_monthly_cents", sa.Integer(), nullable=False),
        sa.Column("spent_monthly_cents", sa.Integer(), nullable=False),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
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
    op.create_index("agents_company_status_idx", "agents", ["org_id", "status"])
    op.create_index("agents_company_reports_to_idx", "agents", ["org_id", "reports_to"])
    op.create_index(
        "agents_org_workspace_key_idx",
        "agents",
        ["org_id", "workspace_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("agents_org_workspace_key_idx", table_name="agents")
    op.drop_index("agents_company_reports_to_idx", table_name="agents")
    op.drop_index("agents_company_status_idx", table_name="agents")
    op.drop_table("agents")
