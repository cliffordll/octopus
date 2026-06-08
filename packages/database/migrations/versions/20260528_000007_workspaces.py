"""add workspace contract tables

Revision ID: 20260528_000007
Revises: 20260528_000006
Create Date: 2026-05-28 00:00:07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from packages.database.migrations.mysql import mysql_text_index_lengths


revision = "20260528_000007"
down_revision = "20260528_000006"
branch_labels = None
depends_on = None


def _timestamp_column(name: str, *, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _json_column(name: str, *, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.JSON(), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "project_workspaces",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("repo_url", sa.Text(), nullable=True),
        sa.Column("repo_ref", sa.Text(), nullable=True),
        sa.Column("default_ref", sa.Text(), nullable=True),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("setup_command", sa.Text(), nullable=True),
        sa.Column("cleanup_command", sa.Text(), nullable=True),
        sa.Column("remote_provider", sa.Text(), nullable=True),
        sa.Column("remote_workspace_ref", sa.Text(), nullable=True),
        sa.Column("shared_workspace_key", sa.Text(), nullable=True),
        _json_column("metadata"),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
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
        "project_workspaces_company_project_idx",
        "project_workspaces",
        ["org_id", "project_id"],
    )
    op.create_index(
        "project_workspaces_project_primary_idx",
        "project_workspaces",
        ["project_id", "is_primary"],
    )
    op.create_index(
        "project_workspaces_project_source_type_idx",
        "project_workspaces",
        ["project_id", "source_type"],
        mysql_length=mysql_text_index_lengths("source_type"),
    )
    op.create_index(
        "project_workspaces_company_shared_key_idx",
        "project_workspaces",
        ["org_id", "shared_workspace_key"],
        mysql_length=mysql_text_index_lengths("shared_workspace_key"),
    )
    op.create_index(
        "project_workspaces_project_remote_ref_idx",
        "project_workspaces",
        ["project_id", "remote_provider", "remote_workspace_ref"],
        unique=True,
        mysql_length=mysql_text_index_lengths(
            "remote_provider", "remote_workspace_ref"
        ),
    )
    op.create_table(
        "execution_workspaces",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_workspace_id",
            sa.String(length=36),
            sa.ForeignKey("project_workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_issue_id",
            sa.String(length=36),
            sa.ForeignKey("issues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("strategy_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("repo_url", sa.Text(), nullable=True),
        sa.Column("base_ref", sa.Text(), nullable=True),
        sa.Column("branch_name", sa.Text(), nullable=True),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.Column(
            "derived_from_execution_workspace_id",
            sa.String(length=36),
            sa.ForeignKey("execution_workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        _timestamp_column("closed_at"),
        _timestamp_column("cleanup_eligible_at"),
        sa.Column("cleanup_reason", sa.Text(), nullable=True),
        _json_column("metadata"),
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
        "execution_workspaces_company_project_status_idx",
        "execution_workspaces",
        ["org_id", "project_id", "status"],
        mysql_length=mysql_text_index_lengths("status"),
    )
    op.create_index(
        "execution_workspaces_company_project_workspace_status_idx",
        "execution_workspaces",
        ["org_id", "project_workspace_id", "status"],
        mysql_length=mysql_text_index_lengths("status"),
    )
    op.create_index(
        "execution_workspaces_company_source_issue_idx",
        "execution_workspaces",
        ["org_id", "source_issue_id"],
    )
    op.create_index(
        "execution_workspaces_company_last_used_idx",
        "execution_workspaces",
        ["org_id", "last_used_at"],
    )
    op.create_index(
        "execution_workspaces_company_branch_idx",
        "execution_workspaces",
        ["org_id", "branch_name"],
        mysql_length=mysql_text_index_lengths("branch_name"),
    )

    op.create_table(
        "workspace_runtime_services",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_workspace_id",
            sa.String(length=36),
            sa.ForeignKey("project_workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "execution_workspace_id",
            sa.String(length=36),
            sa.ForeignKey("execution_workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "issue_id",
            sa.String(length=36),
            sa.ForeignKey("issues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Text(), nullable=True),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("lifecycle", sa.Text(), nullable=False),
        sa.Column("reuse_key", sa.Text(), nullable=True),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_ref", sa.Text(), nullable=True),
        sa.Column(
            "owner_agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "started_by_run_id",
            sa.String(length=36),
            sa.ForeignKey("heartbeat_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        _timestamp_column("stopped_at"),
        _json_column("stop_policy"),
        sa.Column("health_status", sa.Text(), nullable=False),
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
        "workspace_runtime_services_company_workspace_status_idx",
        "workspace_runtime_services",
        ["org_id", "project_workspace_id", "status"],
        mysql_length=mysql_text_index_lengths("status"),
    )
    op.create_index(
        "workspace_runtime_services_company_exec_workspace_status_idx",
        "workspace_runtime_services",
        ["org_id", "execution_workspace_id", "status"],
        mysql_length=mysql_text_index_lengths("status"),
    )
    op.create_index(
        "workspace_runtime_services_company_project_status_idx",
        "workspace_runtime_services",
        ["org_id", "project_id", "status"],
        mysql_length=mysql_text_index_lengths("status"),
    )
    op.create_index(
        "workspace_runtime_services_run_idx",
        "workspace_runtime_services",
        ["started_by_run_id"],
    )
    op.create_index(
        "workspace_runtime_services_company_updated_idx",
        "workspace_runtime_services",
        ["org_id", "updated_at"],
    )

    op.create_table(
        "workspace_operations",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "execution_workspace_id",
            sa.String(length=36),
            sa.ForeignKey("execution_workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "heartbeat_run_id",
            sa.String(length=36),
            sa.ForeignKey("heartbeat_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("cwd", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("log_store", sa.Text(), nullable=True),
        sa.Column("log_ref", sa.Text(), nullable=True),
        sa.Column("log_bytes", sa.BigInteger(), nullable=True),
        sa.Column("log_sha256", sa.Text(), nullable=True),
        sa.Column("log_compressed", sa.Boolean(), nullable=False),
        sa.Column("stdout_excerpt", sa.Text(), nullable=True),
        sa.Column("stderr_excerpt", sa.Text(), nullable=True),
        _json_column("metadata"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        _timestamp_column("finished_at"),
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
        "workspace_operations_company_run_started_idx",
        "workspace_operations",
        ["org_id", "heartbeat_run_id", "started_at"],
    )
    op.create_index(
        "workspace_operations_company_workspace_started_idx",
        "workspace_operations",
        ["org_id", "execution_workspace_id", "started_at"],
    )

    op.create_table(
        "issue_work_products",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "issue_id",
            sa.String(length=36),
            sa.ForeignKey("issues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "execution_workspace_id",
            sa.String(length=36),
            sa.ForeignKey("execution_workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "runtime_service_id",
            sa.String(length=36),
            sa.ForeignKey("workspace_runtime_services.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("review_state", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("health_status", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        _json_column("metadata"),
        sa.Column(
            "created_by_run_id",
            sa.String(length=36),
            sa.ForeignKey("heartbeat_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        "issue_work_products_company_issue_type_idx",
        "issue_work_products",
        ["org_id", "issue_id", "type"],
        mysql_length=mysql_text_index_lengths("type"),
    )
    op.create_index(
        "issue_work_products_company_execution_workspace_type_idx",
        "issue_work_products",
        ["org_id", "execution_workspace_id", "type"],
        mysql_length=mysql_text_index_lengths("type"),
    )
    op.create_index(
        "issue_work_products_company_provider_external_id_idx",
        "issue_work_products",
        ["org_id", "provider", "external_id"],
        mysql_length=mysql_text_index_lengths("provider", "external_id"),
    )
    op.create_index(
        "issue_work_products_company_updated_idx",
        "issue_work_products",
        ["org_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "issue_work_products_company_updated_idx", table_name="issue_work_products"
    )
    op.drop_index(
        "issue_work_products_company_provider_external_id_idx",
        table_name="issue_work_products",
    )
    op.drop_index(
        "issue_work_products_company_execution_workspace_type_idx",
        table_name="issue_work_products",
    )
    op.drop_index(
        "issue_work_products_company_issue_type_idx", table_name="issue_work_products"
    )
    op.drop_table("issue_work_products")

    op.drop_index(
        "workspace_operations_company_workspace_started_idx",
        table_name="workspace_operations",
    )
    op.drop_index(
        "workspace_operations_company_run_started_idx",
        table_name="workspace_operations",
    )
    op.drop_table("workspace_operations")

    op.drop_index(
        "workspace_runtime_services_company_updated_idx",
        table_name="workspace_runtime_services",
    )
    op.drop_index(
        "workspace_runtime_services_run_idx",
        table_name="workspace_runtime_services",
    )
    op.drop_index(
        "workspace_runtime_services_company_project_status_idx",
        table_name="workspace_runtime_services",
    )
    op.drop_index(
        "workspace_runtime_services_company_exec_workspace_status_idx",
        table_name="workspace_runtime_services",
    )
    op.drop_index(
        "workspace_runtime_services_company_workspace_status_idx",
        table_name="workspace_runtime_services",
    )
    op.drop_table("workspace_runtime_services")

    op.drop_index(
        "execution_workspaces_company_branch_idx", table_name="execution_workspaces"
    )
    op.drop_index(
        "execution_workspaces_company_last_used_idx",
        table_name="execution_workspaces",
    )
    op.drop_index(
        "execution_workspaces_company_source_issue_idx",
        table_name="execution_workspaces",
    )
    op.drop_index(
        "execution_workspaces_company_project_workspace_status_idx",
        table_name="execution_workspaces",
    )
    op.drop_index(
        "execution_workspaces_company_project_status_idx",
        table_name="execution_workspaces",
    )
    op.drop_table("execution_workspaces")

    op.drop_index(
        "project_workspaces_company_shared_key_idx", table_name="project_workspaces"
    )
    op.drop_index(
        "project_workspaces_project_source_type_idx", table_name="project_workspaces"
    )
    op.drop_index(
        "project_workspaces_project_primary_idx", table_name="project_workspaces"
    )
    op.drop_index(
        "project_workspaces_company_project_idx", table_name="project_workspaces"
    )
    op.drop_table("project_workspaces")
