"""add organization skills

Revision ID: 20260529_000011
Revises: 20260528_000010
Create Date: 2026-05-29 00:00:11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from packages.database.migrations.mysql import mysql_text_index_lengths


revision = "20260529_000011"
down_revision = "20260528_000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_skills",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column(
            "source_type", sa.Text(), nullable=False, server_default="local_path"
        ),
        sa.Column("source_locator", sa.Text(), nullable=True),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column(
            "trust_level",
            sa.Text(),
            nullable=False,
            server_default="markdown_only",
        ),
        sa.Column(
            "compatibility",
            sa.Text(),
            nullable=False,
            server_default="compatible",
        ),
        sa.Column("file_inventory", sa.JSON(), nullable=False, server_default="[]"),
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
        "organization_skills_org_key_idx",
        "organization_skills",
        ["org_id", "key"],
        unique=True,
        mysql_length=mysql_text_index_lengths("key"),
    )
    op.create_index(
        "organization_skills_org_name_idx",
        "organization_skills",
        ["org_id", "name"],
        mysql_length=mysql_text_index_lengths("name"),
    )


def downgrade() -> None:
    op.drop_index("organization_skills_org_name_idx", table_name="organization_skills")
    op.drop_index("organization_skills_org_key_idx", table_name="organization_skills")
    op.drop_table("organization_skills")
