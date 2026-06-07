from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class RuntimeProvider(Base):
    __tablename__ = "runtime_organization_providers"
    __table_args__ = (
        Index(
            "runtime_organization_providers_org_runtime_provider_idx",
            "org_id",
            "runtime_type",
            "provider_id",
            unique=True,
        ),
        Index(
            "runtime_organization_providers_org_runtime_idx",
            "org_id",
            "runtime_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    runtime_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    npm_package: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(
        "config",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RuntimeModel(Base):
    __tablename__ = "runtime_organization_models"
    __table_args__ = (
        Index(
            "runtime_organization_models_org_runtime_provider_model_idx",
            "org_id",
            "runtime_type",
            "provider_id",
            "model_id",
            unique=True,
        ),
        Index(
            "runtime_organization_models_org_runtime_provider_idx",
            "org_id",
            "runtime_type",
            "provider_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    runtime_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RuntimeGlobalProvider(Base):
    __tablename__ = "runtime_global_providers"
    __table_args__ = (
        Index(
            "runtime_global_providers_runtime_provider_idx",
            "runtime_type",
            "provider_id",
            unique=True,
        ),
        Index("runtime_global_providers_runtime_idx", "runtime_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    runtime_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    npm_package: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(
        "config",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RuntimeGlobalModel(Base):
    __tablename__ = "runtime_global_models"
    __table_args__ = (
        Index(
            "runtime_global_models_runtime_provider_model_idx",
            "runtime_type",
            "provider_id",
            "model_id",
            unique=True,
        ),
        Index(
            "runtime_global_models_runtime_provider_idx",
            "runtime_type",
            "provider_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    runtime_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RuntimeModelDefault(Base):
    __tablename__ = "runtime_model_defaults"
    __table_args__ = (
        Index(
            "runtime_model_defaults_scope_runtime_idx",
            "scope_type",
            "scope_id",
            "runtime_type",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    runtime_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
