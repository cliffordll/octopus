"""add goal management tables

Revision ID: 20260527_000007
Revises: 20260527_000006
Create Date: 2026-05-27 00:00:07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_000007"
down_revision = "20260527_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "parent_id", sa.String(length=36), sa.ForeignKey("goals.id"), nullable=True
        ),
        sa.Column(
            "owner_agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id"),
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
    op.create_index("goals_company_idx", "goals", ["org_id"])
    op.create_table(
        "project_goals",
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "goal_id",
            sa.String(length=36),
            sa.ForeignKey("goals.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
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
    op.create_index("project_goals_project_idx", "project_goals", ["project_id"])
    op.create_index("project_goals_goal_idx", "project_goals", ["goal_id"])
    op.create_index("project_goals_company_idx", "project_goals", ["org_id"])


def downgrade() -> None:
    op.drop_index("project_goals_company_idx", table_name="project_goals")
    op.drop_index("project_goals_goal_idx", table_name="project_goals")
    op.drop_index("project_goals_project_idx", table_name="project_goals")
    op.drop_table("project_goals")
    op.drop_index("goals_company_idx", table_name="goals")
    op.drop_table("goals")
