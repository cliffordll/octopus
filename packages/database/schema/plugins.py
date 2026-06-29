from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class Plugin(Base):
    __tablename__ = "plugins"
    __table_args__ = (
        Index("plugins_plugin_key_unique_idx", "plugin_key", unique=True),
        Index("plugins_status_idx", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="installed")
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_locator: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uninstalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PluginConfig(Base):
    __tablename__ = "plugin_config"
    __table_args__ = (
        Index("plugin_config_plugin_unique_idx", "plugin_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id"), nullable=False
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PluginState(Base):
    __tablename__ = "plugin_state"
    __table_args__ = (
        Index("plugin_state_plugin_key_unique_idx", "plugin_id", "key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id"), nullable=False
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[dict[str, Any] | list[Any] | str | int | float | bool | None] = (
        mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PluginEntity(Base):
    __tablename__ = "plugin_entities"
    __table_args__ = (
        Index(
            "plugin_entities_plugin_external_unique_idx",
            "plugin_id",
            "external_type",
            "external_id",
            unique=True,
        ),
        Index("plugin_entities_local_idx", "local_type", "local_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id"), nullable=False
    )
    external_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    local_type: Mapped[str] = mapped_column(Text, nullable=False)
    local_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PluginJob(Base):
    __tablename__ = "plugin_jobs"
    __table_args__ = (
        Index("plugin_jobs_plugin_key_unique_idx", "plugin_id", "job_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id"), nullable=False
    )
    job_key: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    schedule: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PluginJobRun(Base):
    __tablename__ = "plugin_job_runs"
    __table_args__ = (Index("plugin_job_runs_plugin_job_idx", "plugin_id", "job_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugin_jobs.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PluginLog(Base):
    __tablename__ = "plugin_logs"
    __table_args__ = (
        Index("plugin_logs_plugin_created_idx", "plugin_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id"), nullable=False
    )
    level: Mapped[str] = mapped_column(Text, nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PluginWebhookDelivery(Base):
    __tablename__ = "plugin_webhook_deliveries"
    __table_args__ = (
        Index(
            "plugin_webhook_deliveries_plugin_created_idx", "plugin_id", "created_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id"), nullable=False
    )
    webhook_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="received")
    request_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    response_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PluginOrganizationSetting(Base):
    __tablename__ = "plugin_organization_settings"
    __table_args__ = (
        Index(
            "plugin_organization_settings_plugin_org_unique_idx",
            "plugin_id",
            "org_id",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plugin_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("plugins.id"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
