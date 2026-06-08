from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from packages.database.migrations.mysql import mysql_text_index_lengths


revision = "20260607_000018"
down_revision = "20260605_000017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "mysql":
        op.rename_table("runtime_providers", "runtime_organization_providers")
        op.rename_table("runtime_models", "runtime_organization_models")
        _rename_mysql_index(
            "runtime_organization_models",
            "runtime_models_org_runtime_provider_idx",
            "runtime_organization_models_org_runtime_provider_idx",
        )
        _rename_mysql_index(
            "runtime_organization_models",
            "runtime_models_org_runtime_provider_model_idx",
            "runtime_organization_models_org_runtime_provider_model_idx",
        )
        _rename_mysql_index(
            "runtime_organization_providers",
            "runtime_providers_org_runtime_idx",
            "runtime_organization_providers_org_runtime_idx",
        )
        _rename_mysql_index(
            "runtime_organization_providers",
            "runtime_providers_org_runtime_provider_idx",
            "runtime_organization_providers_org_runtime_provider_idx",
        )
    else:
        op.drop_index(
            "runtime_models_org_runtime_provider_idx", table_name="runtime_models"
        )
        op.drop_index(
            "runtime_models_org_runtime_provider_model_idx", table_name="runtime_models"
        )
        op.drop_index(
            "runtime_providers_org_runtime_idx", table_name="runtime_providers"
        )
        op.drop_index(
            "runtime_providers_org_runtime_provider_idx",
            table_name="runtime_providers",
        )
        op.rename_table("runtime_providers", "runtime_organization_providers")
        op.rename_table("runtime_models", "runtime_organization_models")
        op.create_index(
            "runtime_organization_providers_org_runtime_provider_idx",
            "runtime_organization_providers",
            ["org_id", "runtime_type", "provider_id"],
            unique=True,
            mysql_length=mysql_text_index_lengths("runtime_type", "provider_id"),
        )
        op.create_index(
            "runtime_organization_providers_org_runtime_idx",
            "runtime_organization_providers",
            ["org_id", "runtime_type"],
            mysql_length=mysql_text_index_lengths("runtime_type"),
        )
        op.create_index(
            "runtime_organization_models_org_runtime_provider_model_idx",
            "runtime_organization_models",
            ["org_id", "runtime_type", "provider_id", "model_id"],
            unique=True,
            mysql_length=mysql_text_index_lengths(
                "runtime_type", "provider_id", "model_id"
            ),
        )
        op.create_index(
            "runtime_organization_models_org_runtime_provider_idx",
            "runtime_organization_models",
            ["org_id", "runtime_type", "provider_id"],
            mysql_length=mysql_text_index_lengths("runtime_type", "provider_id"),
        )

    op.create_table(
        "runtime_global_providers",
        sa.Column("id", sa.String(length=36), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "runtime_global_providers_runtime_provider_idx",
        "runtime_global_providers",
        ["runtime_type", "provider_id"],
        unique=True,
        mysql_length=mysql_text_index_lengths("runtime_type", "provider_id"),
    )
    op.create_index(
        "runtime_global_providers_runtime_idx",
        "runtime_global_providers",
        ["runtime_type"],
        mysql_length=mysql_text_index_lengths("runtime_type"),
    )

    op.create_table(
        "runtime_global_models",
        sa.Column("id", sa.String(length=36), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "runtime_global_models_runtime_provider_model_idx",
        "runtime_global_models",
        ["runtime_type", "provider_id", "model_id"],
        unique=True,
        mysql_length=mysql_text_index_lengths(
            "runtime_type", "provider_id", "model_id"
        ),
    )
    op.create_index(
        "runtime_global_models_runtime_provider_idx",
        "runtime_global_models",
        ["runtime_type", "provider_id"],
        mysql_length=mysql_text_index_lengths("runtime_type", "provider_id"),
    )

    op.create_table(
        "runtime_model_defaults",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("runtime_type", sa.Text(), nullable=False),
        sa.Column("provider_scope_type", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "runtime_model_defaults_scope_runtime_idx",
        "runtime_model_defaults",
        ["scope_type", "scope_id", "runtime_type"],
        unique=True,
        mysql_length=mysql_text_index_lengths("scope_type", "runtime_type"),
    )


def _rename_mysql_index(table_name: str, old_name: str, new_name: str) -> None:
    op.execute(
        sa.text(f"ALTER TABLE {table_name} RENAME INDEX {old_name} TO {new_name}")
    )


def _downgrade_renamed_runtime_tables() -> None:
    if op.get_bind().dialect.name == "mysql":
        _rename_mysql_index(
            "runtime_organization_models",
            "runtime_organization_models_org_runtime_provider_idx",
            "runtime_models_org_runtime_provider_idx",
        )
        _rename_mysql_index(
            "runtime_organization_models",
            "runtime_organization_models_org_runtime_provider_model_idx",
            "runtime_models_org_runtime_provider_model_idx",
        )
        _rename_mysql_index(
            "runtime_organization_providers",
            "runtime_organization_providers_org_runtime_idx",
            "runtime_providers_org_runtime_idx",
        )
        _rename_mysql_index(
            "runtime_organization_providers",
            "runtime_organization_providers_org_runtime_provider_idx",
            "runtime_providers_org_runtime_provider_idx",
        )
        op.rename_table("runtime_organization_models", "runtime_models")
        op.rename_table("runtime_organization_providers", "runtime_providers")
        return

    op.drop_index(
        "runtime_organization_models_org_runtime_provider_idx",
        table_name="runtime_organization_models",
    )
    op.drop_index(
        "runtime_organization_models_org_runtime_provider_model_idx",
        table_name="runtime_organization_models",
    )
    op.drop_index(
        "runtime_organization_providers_org_runtime_idx",
        table_name="runtime_organization_providers",
    )
    op.drop_index(
        "runtime_organization_providers_org_runtime_provider_idx",
        table_name="runtime_organization_providers",
    )
    op.rename_table("runtime_organization_models", "runtime_models")
    op.rename_table("runtime_organization_providers", "runtime_providers")
    op.create_index(
        "runtime_models_org_runtime_provider_idx",
        "runtime_models",
        ["org_id", "runtime_type", "provider_id"],
        mysql_length=mysql_text_index_lengths("runtime_type", "provider_id"),
    )
    op.create_index(
        "runtime_models_org_runtime_provider_model_idx",
        "runtime_models",
        ["org_id", "runtime_type", "provider_id", "model_id"],
        unique=True,
        mysql_length=mysql_text_index_lengths(
            "runtime_type", "provider_id", "model_id"
        ),
    )
    op.create_index(
        "runtime_providers_org_runtime_idx",
        "runtime_providers",
        ["org_id", "runtime_type"],
        mysql_length=mysql_text_index_lengths("runtime_type"),
    )
    op.create_index(
        "runtime_providers_org_runtime_provider_idx",
        "runtime_providers",
        ["org_id", "runtime_type", "provider_id"],
        unique=True,
        mysql_length=mysql_text_index_lengths("runtime_type", "provider_id"),
    )


def downgrade() -> None:
    op.drop_index(
        "runtime_model_defaults_scope_runtime_idx",
        table_name="runtime_model_defaults",
    )
    op.drop_table("runtime_model_defaults")
    op.drop_index(
        "runtime_global_models_runtime_provider_idx",
        table_name="runtime_global_models",
    )
    op.drop_index(
        "runtime_global_models_runtime_provider_model_idx",
        table_name="runtime_global_models",
    )
    op.drop_table("runtime_global_models")
    op.drop_index(
        "runtime_global_providers_runtime_idx",
        table_name="runtime_global_providers",
    )
    op.drop_index(
        "runtime_global_providers_runtime_provider_idx",
        table_name="runtime_global_providers",
    )
    op.drop_table("runtime_global_providers")

    _downgrade_renamed_runtime_tables()
