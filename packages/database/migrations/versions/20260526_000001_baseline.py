"""baseline schema

Revision ID: 20260526_000001
Revises:
Create Date: 2026-05-26 00:00:01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from packages.database.migrations.mysql import mysql_text_index_lengths


revision = "20260526_000001"
down_revision = None
branch_labels = None
depends_on = None


_OPEN_AUTOMATION_EXECUTION_WHERE = sa.text(
    "origin_kind = 'automation_execution' "
    "and origin_id is not null "
    "and hidden_at is null "
    "and execution_run_id is not null "
    "and status in ('backlog', 'todo', 'in_progress', 'in_review', 'blocked')"
)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("url_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issue_prefix", sa.Text(), nullable=False),
        sa.Column("issue_counter", sa.Integer(), nullable=False),
        sa.Column("budget_monthly_cents", sa.Integer(), nullable=False),
        sa.Column("spent_monthly_cents", sa.Integer(), nullable=False),
        sa.Column(
            "require_board_approval_for_new_agents", sa.Boolean(), nullable=False
        ),
        sa.Column("default_chat_issue_creation_mode", sa.Text(), nullable=False),
        sa.Column("workspace_config", sa.JSON(), nullable=True),
        sa.Column("brand_color", sa.Text(), nullable=True),
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
        "organizations_url_key_idx",
        "organizations",
        ["url_key"],
        unique=True,
        mysql_length=mysql_text_index_lengths("url_key"),
    )
    op.create_index(
        "organizations_issue_prefix_idx",
        "organizations",
        ["issue_prefix"],
        unique=True,
        mysql_length=mysql_text_index_lengths("issue_prefix"),
    )

    op.create_table(
        "issues",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("project_workspace_id", sa.String(length=36), nullable=True),
        sa.Column("goal_id", sa.String(length=36), nullable=True),
        sa.Column(
            "parent_id", sa.String(length=36), sa.ForeignKey("issues.id"), nullable=True
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("board_order", sa.Integer(), nullable=False),
        sa.Column("assignee_agent_id", sa.String(length=36), nullable=True),
        sa.Column("assignee_user_id", sa.Text(), nullable=True),
        sa.Column("reviewer_agent_id", sa.String(length=36), nullable=True),
        sa.Column("reviewer_user_id", sa.Text(), nullable=True),
        sa.Column("checkout_run_id", sa.String(length=36), nullable=True),
        sa.Column("execution_run_id", sa.String(length=36), nullable=True),
        sa.Column("execution_agent_name_key", sa.Text(), nullable=True),
        sa.Column("execution_locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_agent_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("issue_number", sa.Integer(), nullable=True),
        sa.Column("identifier", sa.Text(), nullable=True),
        sa.Column("origin_kind", sa.Text(), nullable=False),
        sa.Column("origin_id", sa.Text(), nullable=True),
        sa.Column("origin_run_id", sa.Text(), nullable=True),
        sa.Column("request_depth", sa.Integer(), nullable=False),
        sa.Column("billing_code", sa.Text(), nullable=True),
        sa.Column("assignee_agent_runtime_overrides", sa.JSON(), nullable=True),
        sa.Column("execution_workspace_id", sa.String(length=36), nullable=True),
        sa.Column("execution_workspace_preference", sa.Text(), nullable=True),
        sa.Column("execution_workspace_settings", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
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
        "issues_company_status_idx",
        "issues",
        ["org_id", "status"],
        mysql_length=mysql_text_index_lengths("status"),
    )
    op.create_index(
        "issues_company_status_board_order_idx",
        "issues",
        ["org_id", "status", "board_order"],
        mysql_length=mysql_text_index_lengths("status"),
    )
    op.create_index(
        "issues_company_assignee_status_idx",
        "issues",
        ["org_id", "assignee_agent_id", "status"],
        mysql_length=mysql_text_index_lengths("status"),
    )
    op.create_index(
        "issues_company_assignee_user_status_idx",
        "issues",
        ["org_id", "assignee_user_id", "status"],
        mysql_length=mysql_text_index_lengths("assignee_user_id", "status"),
    )
    op.create_index(
        "issues_company_reviewer_agent_status_idx",
        "issues",
        ["org_id", "reviewer_agent_id", "status"],
        mysql_length=mysql_text_index_lengths("status"),
    )
    op.create_index(
        "issues_company_reviewer_user_status_idx",
        "issues",
        ["org_id", "reviewer_user_id", "status"],
        mysql_length=mysql_text_index_lengths("reviewer_user_id", "status"),
    )
    op.create_index("issues_company_parent_idx", "issues", ["org_id", "parent_id"])
    op.create_index("issues_company_project_idx", "issues", ["org_id", "project_id"])
    op.create_index(
        "issues_company_origin_idx",
        "issues",
        ["org_id", "origin_kind", "origin_id"],
        mysql_length=mysql_text_index_lengths("origin_kind", "origin_id"),
    )
    op.create_index(
        "issues_company_project_workspace_idx",
        "issues",
        ["org_id", "project_workspace_id"],
    )
    op.create_index(
        "issues_company_execution_workspace_idx",
        "issues",
        ["org_id", "execution_workspace_id"],
    )
    op.create_index(
        "issues_identifier_idx",
        "issues",
        ["identifier"],
        unique=True,
        mysql_length=mysql_text_index_lengths("identifier"),
    )
    if op.get_bind().dialect.name == "mysql":
        op.create_index(
            "issues_open_automation_execution_uq",
            "issues",
            ["org_id", "origin_kind", "origin_id"],
            unique=False,
            mysql_length=mysql_text_index_lengths("origin_kind", "origin_id"),
        )
    else:
        op.create_index(
            "issues_open_automation_execution_uq",
            "issues",
            ["org_id", "origin_kind", "origin_id"],
            unique=True,
            sqlite_where=_OPEN_AUTOMATION_EXECUTION_WHERE,
            postgresql_where=_OPEN_AUTOMATION_EXECUTION_WHERE,
        )

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("requested_by_agent_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by_user_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
        "approvals_company_status_type_idx",
        "approvals",
        ["org_id", "status", "type"],
        mysql_length=mysql_text_index_lengths("status", "type"),
    )

    op.create_table(
        "issue_comments",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "issue_id", sa.String(length=36), sa.ForeignKey("issues.id"), nullable=False
        ),
        sa.Column("author_agent_id", sa.String(length=36), nullable=True),
        sa.Column("author_user_id", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
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
    op.create_index("issue_comments_issue_idx", "issue_comments", ["issue_id"])
    op.create_index("issue_comments_company_idx", "issue_comments", ["org_id"])
    op.create_index(
        "issue_comments_company_issue_created_at_idx",
        "issue_comments",
        ["org_id", "issue_id", "created_at"],
    )
    op.create_index(
        "issue_comments_company_author_issue_created_at_idx",
        "issue_comments",
        ["org_id", "author_user_id", "issue_id", "created_at"],
        mysql_length=mysql_text_index_lengths("author_user_id"),
    )

    op.create_table(
        "activity_log",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "activity_log_company_created_idx", "activity_log", ["org_id", "created_at"]
    )
    op.create_index("activity_log_run_id_idx", "activity_log", ["run_id"])
    op.create_index(
        "activity_log_entity_type_id_idx",
        "activity_log",
        ["entity_type", "entity_id"],
        mysql_length=mysql_text_index_lengths("entity_type", "entity_id"),
    )

    op.create_table(
        "issue_approvals",
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "issue_id",
            sa.String(length=36),
            sa.ForeignKey("issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "approval_id",
            sa.String(length=36),
            sa.ForeignKey("approvals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("linked_by_agent_id", sa.String(length=36), nullable=True),
        sa.Column("linked_by_user_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("issue_id", "approval_id", name="issue_approvals_pk"),
    )
    op.create_index("issue_approvals_issue_idx", "issue_approvals", ["issue_id"])
    op.create_index("issue_approvals_approval_idx", "issue_approvals", ["approval_id"])
    op.create_index("issue_approvals_company_idx", "issue_approvals", ["org_id"])


def downgrade() -> None:
    op.drop_index("issue_approvals_company_idx", table_name="issue_approvals")
    op.drop_index("issue_approvals_approval_idx", table_name="issue_approvals")
    op.drop_index("issue_approvals_issue_idx", table_name="issue_approvals")
    op.drop_table("issue_approvals")

    op.drop_index("activity_log_entity_type_id_idx", table_name="activity_log")
    op.drop_index("activity_log_run_id_idx", table_name="activity_log")
    op.drop_index("activity_log_company_created_idx", table_name="activity_log")
    op.drop_table("activity_log")

    op.drop_index(
        "issue_comments_company_author_issue_created_at_idx",
        table_name="issue_comments",
    )
    op.drop_index(
        "issue_comments_company_issue_created_at_idx", table_name="issue_comments"
    )
    op.drop_index("issue_comments_company_idx", table_name="issue_comments")
    op.drop_index("issue_comments_issue_idx", table_name="issue_comments")
    op.drop_table("issue_comments")

    op.drop_index("approvals_company_status_type_idx", table_name="approvals")
    op.drop_table("approvals")

    op.drop_index("issues_open_automation_execution_uq", table_name="issues")
    op.drop_index("issues_identifier_idx", table_name="issues")
    op.drop_index("issues_company_execution_workspace_idx", table_name="issues")
    op.drop_index("issues_company_project_workspace_idx", table_name="issues")
    op.drop_index("issues_company_origin_idx", table_name="issues")
    op.drop_index("issues_company_project_idx", table_name="issues")
    op.drop_index("issues_company_parent_idx", table_name="issues")
    op.drop_index("issues_company_reviewer_user_status_idx", table_name="issues")
    op.drop_index("issues_company_reviewer_agent_status_idx", table_name="issues")
    op.drop_index("issues_company_assignee_user_status_idx", table_name="issues")
    op.drop_index("issues_company_assignee_status_idx", table_name="issues")
    op.drop_index("issues_company_status_board_order_idx", table_name="issues")
    op.drop_index("issues_company_status_idx", table_name="issues")
    op.drop_table("issues")

    op.drop_index("organizations_issue_prefix_idx", table_name="organizations")
    op.drop_index("organizations_url_key_idx", table_name="organizations")
    op.drop_table("organizations")
