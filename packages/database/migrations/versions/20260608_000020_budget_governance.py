from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260608_000020"
down_revision = "20260608_000019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("window_kind", sa.Text(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("warn_percent", sa.Integer(), nullable=False),
        sa.Column("hard_stop_enabled", sa.Boolean(), nullable=False),
        sa.Column("notify_enabled", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("updated_by_user_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "budget_policies_company_scope_active_idx",
        "budget_policies",
        ["org_id", "scope_type", "scope_id", "is_active"],
    )
    op.create_index(
        "budget_policies_company_window_idx",
        "budget_policies",
        ["org_id", "window_kind", "metric"],
    )
    op.create_index(
        "budget_policies_company_scope_metric_unique_idx",
        "budget_policies",
        ["org_id", "scope_type", "scope_id", "metric", "window_kind"],
        unique=True,
    )

    op.create_table(
        "budget_incidents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("window_kind", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("threshold_type", sa.Text(), nullable=False),
        sa.Column("amount_limit", sa.Integer(), nullable=False),
        sa.Column("amount_observed", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["budget_policies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "budget_incidents_company_status_idx",
        "budget_incidents",
        ["org_id", "status"],
    )
    op.create_index(
        "budget_incidents_company_scope_idx",
        "budget_incidents",
        ["org_id", "scope_type", "scope_id", "status"],
    )
    op.create_index(
        "budget_incidents_policy_window_threshold_idx",
        "budget_incidents",
        ["policy_id", "window_start", "threshold_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "budget_incidents_policy_window_threshold_idx",
        table_name="budget_incidents",
    )
    op.drop_index("budget_incidents_company_scope_idx", table_name="budget_incidents")
    op.drop_index("budget_incidents_company_status_idx", table_name="budget_incidents")
    op.drop_table("budget_incidents")
    op.drop_index(
        "budget_policies_company_scope_metric_unique_idx",
        table_name="budget_policies",
    )
    op.drop_index("budget_policies_company_window_idx", table_name="budget_policies")
    op.drop_index(
        "budget_policies_company_scope_active_idx",
        table_name="budget_policies",
    )
    op.drop_table("budget_policies")
