from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260610_000021"
down_revision = "20260608_000020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("protocol", sa.Text(), nullable=False),
        sa.Column("npm_package", sa.Text(), nullable=True),
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
        "llm_providers_provider_idx", "llm_providers", ["provider_id"], unique=True
    )
    op.create_table(
        "llm_provider_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["provider_id"], ["llm_providers.provider_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "llm_provider_bindings_scope_provider_idx",
        "llm_provider_bindings",
        ["scope_type", "scope_id", "provider_id"],
        unique=True,
    )
    op.create_index(
        "llm_provider_bindings_provider_idx",
        "llm_provider_bindings",
        ["provider_id"],
    )
    op.create_table(
        "llm_models",
        sa.Column("id", sa.String(length=36), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["provider_id"], ["llm_providers.provider_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "llm_models_provider_model_idx",
        "llm_models",
        ["provider_id", "model_id"],
        unique=True,
    )
    op.create_index("llm_models_provider_idx", "llm_models", ["provider_id"])
    op.create_table(
        "llm_runtime_defaults",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("runtime_type", sa.Text(), nullable=False),
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
        "llm_runtime_defaults_scope_runtime_idx",
        "llm_runtime_defaults",
        ["scope_type", "scope_id", "runtime_type"],
        unique=True,
    )
    op.create_index(
        "llm_runtime_defaults_provider_model_idx",
        "llm_runtime_defaults",
        ["provider_id", "model_id"],
    )
    _migrate_existing_runtime_provider_data()
    _drop_old_runtime_provider_tables()


def downgrade() -> None:
    op.drop_index(
        "llm_runtime_defaults_provider_model_idx", table_name="llm_runtime_defaults"
    )
    op.drop_index(
        "llm_runtime_defaults_scope_runtime_idx", table_name="llm_runtime_defaults"
    )
    op.drop_table("llm_runtime_defaults")
    op.drop_index("llm_models_provider_idx", table_name="llm_models")
    op.drop_index("llm_models_provider_model_idx", table_name="llm_models")
    op.drop_table("llm_models")
    op.drop_index("llm_provider_bindings_provider_idx", table_name="llm_provider_bindings")
    op.drop_index(
        "llm_provider_bindings_scope_provider_idx",
        table_name="llm_provider_bindings",
    )
    op.drop_table("llm_provider_bindings")
    op.drop_index("llm_providers_provider_idx", table_name="llm_providers")
    op.drop_table("llm_providers")


def _migrate_existing_runtime_provider_data() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "runtime_global_providers" in tables:
        bind.execute(
            sa.text(
                """
                insert into llm_providers (
                    id, provider_id, name, protocol, npm_package, enabled,
                    created_at, updated_at
                )
                select id, provider_id, name, protocol, npm_package, enabled,
                       created_at, updated_at
                from runtime_global_providers
                where provider_id not in (select provider_id from llm_providers)
                """
            )
        )
        bind.execute(
            sa.text(
                """
                insert into llm_provider_bindings (
                    id, scope_type, scope_id, provider_id, base_url, api_key,
                    config, enabled, priority, created_at, updated_at
                )
                select id, 'instance', '', provider_id, base_url, api_key,
                       config, enabled, 0, created_at, updated_at
                from runtime_global_providers
                where not exists (
                    select 1 from llm_provider_bindings b
                    where b.scope_type = 'instance'
                      and b.scope_id = ''
                      and b.provider_id = runtime_global_providers.provider_id
                )
                """
            )
        )
    if "runtime_organization_providers" in tables:
        bind.execute(
            sa.text(
                """
                insert into llm_providers (
                    id, provider_id, name, protocol, npm_package, enabled,
                    created_at, updated_at
                )
                select id, provider_id, name, protocol, npm_package, enabled,
                       created_at, updated_at
                from runtime_organization_providers
                where provider_id not in (select provider_id from llm_providers)
                """
            )
        )
        bind.execute(
            sa.text(
                """
                insert into llm_provider_bindings (
                    id, scope_type, scope_id, provider_id, base_url, api_key,
                    config, enabled, priority, created_at, updated_at
                )
                select id, 'organization', org_id, provider_id, base_url, api_key,
                       config, enabled, 0, created_at, updated_at
                from runtime_organization_providers
                """
            )
        )
    if "runtime_global_models" in tables:
        bind.execute(
            sa.text(
                """
                insert into llm_models (
                    id, provider_id, model_id, display_name, metadata, enabled,
                    created_at, updated_at
                )
                select id, provider_id, model_id, display_name, metadata, enabled,
                       created_at, updated_at
                from runtime_global_models
                where not exists (
                    select 1 from llm_models m
                    where m.provider_id = runtime_global_models.provider_id
                      and m.model_id = runtime_global_models.model_id
                )
                """
            )
        )
    if "runtime_organization_models" in tables:
        bind.execute(
            sa.text(
                """
                insert into llm_models (
                    id, provider_id, model_id, display_name, metadata, enabled,
                    created_at, updated_at
                )
                select id, provider_id, model_id, display_name, metadata, enabled,
                       created_at, updated_at
                from runtime_organization_models
                where not exists (
                    select 1 from llm_models m
                    where m.provider_id = runtime_organization_models.provider_id
                      and m.model_id = runtime_organization_models.model_id
                )
                """
            )
        )
    if "runtime_model_defaults" in tables:
        bind.execute(
            sa.text(
                """
                insert into llm_runtime_defaults (
                    id, scope_type, scope_id, runtime_type, provider_id, model_id,
                    created_at, updated_at
                )
                select id,
                       case when scope_type = 'global' then 'instance' else scope_type end,
                       scope_id,
                       runtime_type,
                       provider_id,
                       model_id,
                       created_at,
                       updated_at
                from runtime_model_defaults
                """
            )
        )


def _drop_old_runtime_provider_tables() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "runtime_model_defaults" in tables:
        op.drop_index(
            "runtime_model_defaults_scope_runtime_idx",
            table_name="runtime_model_defaults",
        )
        op.drop_table("runtime_model_defaults")
    if "runtime_global_models" in tables:
        op.drop_index(
            "runtime_global_models_runtime_provider_idx",
            table_name="runtime_global_models",
        )
        op.drop_index(
            "runtime_global_models_runtime_provider_model_idx",
            table_name="runtime_global_models",
        )
        op.drop_table("runtime_global_models")
    if "runtime_global_providers" in tables:
        op.drop_index(
            "runtime_global_providers_runtime_idx",
            table_name="runtime_global_providers",
        )
        op.drop_index(
            "runtime_global_providers_runtime_provider_idx",
            table_name="runtime_global_providers",
        )
        op.drop_table("runtime_global_providers")
    if "runtime_organization_models" in tables:
        op.drop_index(
            "runtime_organization_models_org_runtime_provider_idx",
            table_name="runtime_organization_models",
        )
        op.drop_index(
            "runtime_organization_models_org_runtime_provider_model_idx",
            table_name="runtime_organization_models",
        )
        op.drop_table("runtime_organization_models")
    if "runtime_organization_providers" in tables:
        op.drop_index(
            "runtime_organization_providers_org_runtime_idx",
            table_name="runtime_organization_providers",
        )
        op.drop_index(
            "runtime_organization_providers_org_runtime_provider_idx",
            table_name="runtime_organization_providers",
        )
        op.drop_table("runtime_organization_providers")
