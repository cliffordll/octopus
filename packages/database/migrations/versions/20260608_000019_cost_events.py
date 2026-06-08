from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260608_000019"
down_revision = "20260607_000018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cost_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("runtime_type", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("biller", sa.Text(), nullable=True),
        sa.Column("cost_cents", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "cost_events_org_occurred_idx", "cost_events", ["org_id", "occurred_at"]
    )
    op.create_index(
        "cost_events_org_agent_occurred_idx",
        "cost_events",
        ["org_id", "agent_id", "occurred_at"],
    )
    op.create_index(
        "cost_events_org_project_occurred_idx",
        "cost_events",
        ["org_id", "project_id", "occurred_at"],
    )
    op.create_index("cost_events_org_provider_idx", "cost_events", ["org_id", "provider"])
    op.create_index("cost_events_org_biller_idx", "cost_events", ["org_id", "biller"])
    op.create_index(
        "cost_events_org_source_idx",
        "cost_events",
        ["org_id", "source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("cost_events_org_source_idx", table_name="cost_events")
    op.drop_index("cost_events_org_biller_idx", table_name="cost_events")
    op.drop_index("cost_events_org_provider_idx", table_name="cost_events")
    op.drop_index("cost_events_org_project_occurred_idx", table_name="cost_events")
    op.drop_index("cost_events_org_agent_occurred_idx", table_name="cost_events")
    op.drop_index("cost_events_org_occurred_idx", table_name="cost_events")
    op.drop_table("cost_events")
