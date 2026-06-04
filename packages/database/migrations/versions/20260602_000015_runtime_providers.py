from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260602_000015"
down_revision = "20260529_000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_providers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("runtime_type", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("protocol", sa.Text(), nullable=False),
        sa.Column("npm_package", sa.Text(), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "runtime_providers_org_runtime_provider_idx",
        "runtime_providers",
        ["org_id", "runtime_type", "provider_id"],
        unique=True,
    )
    op.create_index(
        "runtime_providers_org_runtime_idx",
        "runtime_providers",
        ["org_id", "runtime_type"],
    )

    op.create_table(
        "runtime_models",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("runtime_type", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "runtime_models_org_runtime_provider_model_idx",
        "runtime_models",
        ["org_id", "runtime_type", "provider_id", "model_id"],
        unique=True,
    )
    op.create_index(
        "runtime_models_org_runtime_provider_idx",
        "runtime_models",
        ["org_id", "runtime_type", "provider_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "runtime_models_org_runtime_provider_idx", table_name="runtime_models"
    )
    op.drop_index(
        "runtime_models_org_runtime_provider_model_idx", table_name="runtime_models"
    )
    op.drop_table("runtime_models")
    op.drop_index("runtime_providers_org_runtime_idx", table_name="runtime_providers")
    op.drop_index(
        "runtime_providers_org_runtime_provider_idx", table_name="runtime_providers"
    )
    op.drop_table("runtime_providers")
