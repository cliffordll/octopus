"""add chat conversation and message tables

Revision ID: 20260527_000006
Revises: 20260527_000005
Create Date: 2026-05-27 00:00:06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_000006"
down_revision = "20260527_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "preferred_agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "routed_agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "primary_issue_id",
            sa.String(length=36),
            sa.ForeignKey("issues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("issue_creation_mode", sa.Text(), nullable=False),
        sa.Column("plan_mode", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        "chat_conversations_org_updated_idx",
        "chat_conversations",
        ["org_id", "updated_at"],
    )
    op.create_index(
        "chat_conversations_org_status_updated_idx",
        "chat_conversations",
        ["org_id", "status", "updated_at"],
    )
    op.create_index(
        "chat_conversations_primary_issue_idx",
        "chat_conversations",
        ["primary_issue_id"],
    )
    op.create_table(
        "chat_messages",
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
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("structured_payload", sa.JSON(), nullable=True),
        sa.Column(
            "approval_id",
            sa.String(length=36),
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "replying_agent_id",
            sa.String(length=36),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("chat_turn_id", sa.String(length=36), nullable=True),
        sa.Column("turn_variant", sa.Integer(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
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
        "chat_messages_conversation_created_idx",
        "chat_messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "chat_messages_org_conversation_created_idx",
        "chat_messages",
        ["org_id", "conversation_id", "created_at"],
    )
    op.create_index("chat_messages_approval_idx", "chat_messages", ["approval_id"])


def downgrade() -> None:
    op.drop_index("chat_messages_approval_idx", table_name="chat_messages")
    op.drop_index(
        "chat_messages_org_conversation_created_idx", table_name="chat_messages"
    )
    op.drop_index("chat_messages_conversation_created_idx", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(
        "chat_conversations_primary_issue_idx", table_name="chat_conversations"
    )
    op.drop_index(
        "chat_conversations_org_status_updated_idx", table_name="chat_conversations"
    )
    op.drop_index("chat_conversations_org_updated_idx", table_name="chat_conversations")
    op.drop_table("chat_conversations")
