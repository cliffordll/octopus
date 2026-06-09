from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260609_000021"
down_revision = "20260608_000020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugins",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_locator", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column(
            "installed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uninstalled_at", sa.DateTime(timezone=True), nullable=True),
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
        "plugins_plugin_key_unique_idx", "plugins", ["plugin_key"], unique=True
    )
    op.create_index("plugins_status_idx", "plugins", ["status"])

    op.create_table(
        "plugin_config",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "plugin_config_plugin_unique_idx", "plugin_config", ["plugin_id"], unique=True
    )

    op.create_table(
        "plugin_state",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "plugin_state_plugin_key_unique_idx",
        "plugin_state",
        ["plugin_id", "key"],
        unique=True,
    )

    op.create_table(
        "plugin_entities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("external_type", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("local_type", sa.Text(), nullable=False),
        sa.Column("local_id", sa.String(length=36), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "plugin_entities_plugin_external_unique_idx",
        "plugin_entities",
        ["plugin_id", "external_type", "external_id"],
        unique=True,
    )
    op.create_index(
        "plugin_entities_local_idx", "plugin_entities", ["local_type", "local_id"]
    )

    op.create_table(
        "plugin_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("job_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("schedule", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "plugin_jobs_plugin_key_unique_idx",
        "plugin_jobs",
        ["plugin_id", "job_key"],
        unique=True,
    )

    op.create_table(
        "plugin_job_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["plugin_jobs.id"]),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "plugin_job_runs_plugin_job_idx", "plugin_job_runs", ["plugin_id", "job_id"]
    )

    op.create_table(
        "plugin_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "plugin_logs_plugin_created_idx", "plugin_logs", ["plugin_id", "created_at"]
    )

    op.create_table(
        "plugin_webhook_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("webhook_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=True),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "plugin_webhook_deliveries_plugin_created_idx",
        "plugin_webhook_deliveries",
        ["plugin_id", "created_at"],
    )

    op.create_table(
        "plugin_organization_settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "plugin_organization_settings_plugin_org_unique_idx",
        "plugin_organization_settings",
        ["plugin_id", "org_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "plugin_organization_settings_plugin_org_unique_idx",
        table_name="plugin_organization_settings",
    )
    op.drop_table("plugin_organization_settings")
    op.drop_index(
        "plugin_webhook_deliveries_plugin_created_idx",
        table_name="plugin_webhook_deliveries",
    )
    op.drop_table("plugin_webhook_deliveries")
    op.drop_index("plugin_logs_plugin_created_idx", table_name="plugin_logs")
    op.drop_table("plugin_logs")
    op.drop_index("plugin_job_runs_plugin_job_idx", table_name="plugin_job_runs")
    op.drop_table("plugin_job_runs")
    op.drop_index("plugin_jobs_plugin_key_unique_idx", table_name="plugin_jobs")
    op.drop_table("plugin_jobs")
    op.drop_index("plugin_entities_local_idx", table_name="plugin_entities")
    op.drop_index(
        "plugin_entities_plugin_external_unique_idx", table_name="plugin_entities"
    )
    op.drop_table("plugin_entities")
    op.drop_index("plugin_state_plugin_key_unique_idx", table_name="plugin_state")
    op.drop_table("plugin_state")
    op.drop_index("plugin_config_plugin_unique_idx", table_name="plugin_config")
    op.drop_table("plugin_config")
    op.drop_index("plugins_status_idx", table_name="plugins")
    op.drop_index("plugins_plugin_key_unique_idx", table_name="plugins")
    op.drop_table("plugins")
