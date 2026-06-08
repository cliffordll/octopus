"""add chat attachments

Revision ID: 20260529_000012
Revises: 20260529_000011
Create Date: 2026-05-29 00:00:12
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from packages.database.migrations.mysql import mysql_text_index_lengths


revision = "20260529_000012"
down_revision = "20260529_000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column(
            "created_by_agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id"),
            nullable=True,
        ),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
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
    op.create_index("assets_company_created_idx", "assets", ["org_id", "created_at"])
    op.create_index(
        "assets_company_provider_idx",
        "assets",
        ["org_id", "provider"],
        mysql_length=mysql_text_index_lengths("provider"),
    )
    op.create_index(
        "assets_company_object_key_uq",
        "assets",
        ["org_id", "object_key"],
        unique=True,
        mysql_length=mysql_text_index_lengths("object_key"),
    )

    op.create_table(
        "chat_attachments",
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
        sa.Column(
            "message_id",
            sa.String(length=36),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            sa.String(length=36),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
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
    op.create_index(
        "chat_attachments_conversation_message_idx",
        "chat_attachments",
        ["conversation_id", "message_id"],
    )
    op.create_index(
        "chat_attachments_company_conversation_idx",
        "chat_attachments",
        ["org_id", "conversation_id"],
    )
    op.create_index("chat_attachments_asset_idx", "chat_attachments", ["asset_id"])


def downgrade() -> None:
    op.drop_index("chat_attachments_asset_idx", table_name="chat_attachments")
    op.drop_index(
        "chat_attachments_company_conversation_idx", table_name="chat_attachments"
    )
    op.drop_index(
        "chat_attachments_conversation_message_idx", table_name="chat_attachments"
    )
    op.drop_table("chat_attachments")
    op.drop_index("assets_company_object_key_uq", table_name="assets")
    op.drop_index("assets_company_provider_idx", table_name="assets")
    op.drop_index("assets_company_created_idx", table_name="assets")
    op.drop_table("assets")
