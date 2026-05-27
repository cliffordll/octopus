"""add project management tables

Revision ID: 20260527_000002
Revises: 20260526_000001
Create Date: 2026-05-27 00:00:02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_000002"
down_revision = "20260526_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("goal_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("lead_agent_id", sa.String(length=36), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_workspace_policy", sa.JSON(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("projects_company_idx", "projects", ["org_id"])

    op.create_table(
        "organization_resources",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
    op.create_index(
        "organization_resources_org_idx", "organization_resources", ["org_id"]
    )
    op.create_index(
        "organization_resources_org_kind_idx",
        "organization_resources",
        ["org_id", "kind"],
    )

    op.create_table(
        "project_resource_attachments",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            sa.String(length=36),
            sa.ForeignKey("organization_resources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
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
        "project_resource_attachments_org_project_idx",
        "project_resource_attachments",
        ["org_id", "project_id"],
    )
    op.create_index(
        "project_resource_attachments_resource_idx",
        "project_resource_attachments",
        ["resource_id"],
    )
    op.create_index(
        "project_resource_attachments_project_resource_idx",
        "project_resource_attachments",
        ["project_id", "resource_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "project_resource_attachments_project_resource_idx",
        table_name="project_resource_attachments",
    )
    op.drop_index(
        "project_resource_attachments_resource_idx",
        table_name="project_resource_attachments",
    )
    op.drop_index(
        "project_resource_attachments_org_project_idx",
        table_name="project_resource_attachments",
    )
    op.drop_table("project_resource_attachments")
    op.drop_index(
        "organization_resources_org_kind_idx", table_name="organization_resources"
    )
    op.drop_index("organization_resources_org_idx", table_name="organization_resources")
    op.drop_table("organization_resources")
    op.drop_index("projects_company_idx", table_name="projects")
    op.drop_table("projects")
