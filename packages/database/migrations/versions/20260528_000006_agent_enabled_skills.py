"""add agent enabled skills

Revision ID: 20260528_000006
Revises: 20260527_000007
Create Date: 2026-05-28 00:00:06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from packages.database.migrations.mysql import mysql_text_index_lengths


revision = "20260528_000006"
down_revision = "20260527_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_enabled_skills",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "agent_enabled_skills_agent_idx", "agent_enabled_skills", ["agent_id"]
    )
    op.create_index("agent_enabled_skills_org_idx", "agent_enabled_skills", ["org_id"])
    op.create_index(
        "agent_enabled_skills_agent_skill_idx",
        "agent_enabled_skills",
        ["agent_id", "skill_key"],
        unique=True,
        mysql_length=mysql_text_index_lengths("skill_key"),
    )


def downgrade() -> None:
    op.drop_index(
        "agent_enabled_skills_agent_skill_idx", table_name="agent_enabled_skills"
    )
    op.drop_index("agent_enabled_skills_org_idx", table_name="agent_enabled_skills")
    op.drop_index("agent_enabled_skills_agent_idx", table_name="agent_enabled_skills")
    op.drop_table("agent_enabled_skills")
