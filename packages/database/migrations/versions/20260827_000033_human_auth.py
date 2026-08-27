"""Add human authentication, external bindings, and invites.

Revision ID: 20260827_000033
Revises: 20260827_000032
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260827_000033"
down_revision = "20260827_000032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "session" not in tables:
        op.create_table(
            "session",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("token", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ip_address", sa.Text(), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if "account" not in tables:
        op.create_table(
            "account",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("account_id", sa.Text(), nullable=False),
            sa.Column("provider_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("access_token", sa.Text(), nullable=True),
            sa.Column("refresh_token", sa.Text(), nullable=True),
            sa.Column("id_token", sa.Text(), nullable=True),
            sa.Column(
                "access_token_expires_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.Column(
                "refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column("password", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    if "verification" not in tables:
        op.create_table(
            "verification",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("identifier", sa.Text(), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if "external_user_bindings" not in tables:
        op.create_table(
            "external_user_bindings",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("issuer", sa.Text(), nullable=False),
            sa.Column("subject", sa.Text(), nullable=False),
            sa.Column("local_user_id", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "last_verified_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["local_user_id"], ["user.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "issuer", "subject", name="external_user_bindings_issuer_subject_uq"
            ),
        )
        op.create_index(
            "external_user_bindings_local_user_idx",
            "external_user_bindings",
            ["local_user_id"],
        )
    if "invites" not in tables:
        op.create_table(
            "invites",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("org_id", sa.String(36), nullable=True),
            sa.Column(
                "invite_type", sa.Text(), nullable=False, server_default="company_join"
            ),
            sa.Column("token_hash", sa.Text(), nullable=False),
            sa.Column(
                "allowed_join_types", sa.Text(), nullable=False, server_default="both"
            ),
            sa.Column(
                "defaults_payload",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=True,
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("invited_by_user_id", sa.Text(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="invites_token_hash_unique_idx"),
        )
        op.create_index(
            "invites_company_invite_state_idx",
            "invites",
            ["org_id", "invite_type", "revoked_at", "expires_at"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "invites" in tables:
        op.drop_index("invites_company_invite_state_idx", table_name="invites")
        op.drop_table("invites")
    if "external_user_bindings" in tables:
        op.drop_index(
            "external_user_bindings_local_user_idx", table_name="external_user_bindings"
        )
        op.drop_table("external_user_bindings")
    for table_name in ("verification", "account", "session"):
        if table_name in tables:
            op.drop_table(table_name)
