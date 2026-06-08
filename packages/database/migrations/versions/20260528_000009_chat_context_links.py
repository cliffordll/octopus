"""add chat context links table

Revision ID: 20260528_000009
Revises: 20260528_000008
Create Date: 2026-05-28 00:00:09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from packages.database.migrations.mysql import mysql_text_index_lengths


revision = "20260528_000009"
down_revision = "20260528_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_context_links",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
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
        "chat_context_links_unique_conversation_entity_idx",
        "chat_context_links",
        ["conversation_id", "entity_type", "entity_id"],
        unique=True,
        mysql_length=mysql_text_index_lengths("entity_type", "entity_id"),
    )
    op.create_index(
        "chat_context_links_conversation_entity_idx",
        "chat_context_links",
        ["conversation_id", "entity_type", "entity_id"],
        mysql_length=mysql_text_index_lengths("entity_type", "entity_id"),
    )
    op.create_index(
        "chat_context_links_company_entity_idx",
        "chat_context_links",
        ["org_id", "entity_type", "entity_id"],
        mysql_length=mysql_text_index_lengths("entity_type", "entity_id"),
    )


def downgrade() -> None:
    op.drop_index(
        "chat_context_links_company_entity_idx", table_name="chat_context_links"
    )
    op.drop_index(
        "chat_context_links_conversation_entity_idx", table_name="chat_context_links"
    )
    op.drop_table("chat_context_links")
