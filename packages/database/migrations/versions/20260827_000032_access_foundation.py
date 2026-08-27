"""Add user, organization membership, and access foundation tables.

Revision ID: 20260827_000032
Revises: 20260826_000031
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260827_000032"
down_revision = "20260826_000031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "user" not in tables:
        op.create_table(
            "user",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("email", sa.Text(), nullable=False),
            sa.Column(
                "email_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("image", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "organization_memberships" not in tables:
        op.create_table(
            "organization_memberships",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("org_id", sa.String(length=36), nullable=False),
            sa.Column("principal_type", sa.Text(), nullable=False),
            sa.Column("principal_id", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="active"),
            sa.Column("membership_role", sa.Text(), nullable=True),
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
            sa.UniqueConstraint(
                "org_id",
                "principal_type",
                "principal_id",
                name="organization_memberships_org_principal_unique_idx",
            ),
        )
        op.create_index(
            "organization_memberships_principal_status_idx",
            "organization_memberships",
            ["principal_type", "principal_id", "status"],
        )
        op.create_index(
            "organization_memberships_org_status_idx",
            "organization_memberships",
            ["org_id", "status"],
        )

    if "principal_permission_grants" not in tables:
        op.create_table(
            "principal_permission_grants",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("org_id", sa.String(length=36), nullable=False),
            sa.Column("principal_type", sa.Text(), nullable=False),
            sa.Column("principal_id", sa.Text(), nullable=False),
            sa.Column("permission_key", sa.Text(), nullable=False),
            sa.Column(
                "scope",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=True,
            ),
            sa.Column("granted_by_user_id", sa.Text(), nullable=True),
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
            sa.UniqueConstraint(
                "org_id",
                "principal_type",
                "principal_id",
                "permission_key",
                name="principal_permission_grants_unique_idx",
            ),
        )
        op.create_index(
            "principal_permission_grants_company_permission_idx",
            "principal_permission_grants",
            ["org_id", "permission_key"],
        )

    if "instance_user_roles" not in tables:
        op.create_table(
            "instance_user_roles",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column(
                "role",
                sa.Text(),
                nullable=False,
                server_default="instance_admin",
            ),
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
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id",
                "role",
                name="instance_user_roles_user_role_unique_idx",
            ),
        )
        op.create_index(
            "instance_user_roles_role_idx",
            "instance_user_roles",
            ["role"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "instance_user_roles" in tables:
        op.drop_index("instance_user_roles_role_idx", table_name="instance_user_roles")
        op.drop_table("instance_user_roles")
    if "principal_permission_grants" in tables:
        op.drop_index(
            "principal_permission_grants_company_permission_idx",
            table_name="principal_permission_grants",
        )
        op.drop_table("principal_permission_grants")
    if "organization_memberships" in tables:
        op.drop_index(
            "organization_memberships_org_status_idx",
            table_name="organization_memberships",
        )
        op.drop_index(
            "organization_memberships_principal_status_idx",
            table_name="organization_memberships",
        )
        op.drop_table("organization_memberships")
    if "user" in tables:
        op.drop_table("user")
