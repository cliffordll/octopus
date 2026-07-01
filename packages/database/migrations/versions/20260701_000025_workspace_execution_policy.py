"""move execution policy from projects to project workspaces

Revision ID: 20260701_000025
Revises: 20260619_000024
Create Date: 2026-07-01 00:00:25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260701_000025"
down_revision = "20260619_000024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_workspaces",
        sa.Column("execution_workspace_policy", sa.JSON(), nullable=True),
    )
    op.create_index(
        "project_workspaces_one_primary_uq",
        "project_workspaces",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        sqlite_where=sa.text("is_primary = 1"),
    )
    op.drop_column("projects", "execution_workspace_policy")


def downgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("execution_workspace_policy", sa.JSON(), nullable=True),
    )
    op.drop_index("project_workspaces_one_primary_uq", table_name="project_workspaces")
    op.drop_column("project_workspaces", "execution_workspace_policy")
