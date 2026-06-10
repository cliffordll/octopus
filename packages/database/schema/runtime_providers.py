from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class LlmProvider(Base):
    __tablename__ = "llm_providers"
    __table_args__ = (
        Index("llm_providers_provider_idx", "provider_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    npm_package: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LlmModel(Base):
    __tablename__ = "llm_models"
    __table_args__ = (
        Index(
            "llm_models_provider_model_idx",
            "provider_id",
            "model_id",
            unique=True,
        ),
        Index("llm_models_provider_idx", "provider_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    provider_id: Mapped[str] = mapped_column(
        Text, ForeignKey("llm_providers.provider_id", ondelete="CASCADE"), nullable=False
    )
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


class LlmProviderBinding(Base):
    __tablename__ = "llm_provider_bindings"
    __table_args__ = (
        Index(
            "llm_provider_bindings_scope_provider_idx",
            "scope_type",
            "scope_id",
            "provider_id",
            unique=True,
        ),
        Index("llm_provider_bindings_provider_idx", "provider_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    provider_id: Mapped[str] = mapped_column(
        Text, ForeignKey("llm_providers.provider_id", ondelete="CASCADE"), nullable=False
    )
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(
        "config",
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LlmRuntimeDefault(Base):
    __tablename__ = "llm_runtime_defaults"
    __table_args__ = (
        Index(
            "llm_runtime_defaults_scope_runtime_idx",
            "scope_type",
            "scope_id",
            "runtime_type",
            unique=True,
        ),
        Index("llm_runtime_defaults_provider_model_idx", "provider_id", "model_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False, default="")
    runtime_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Backwards-compatible Python names while the service/module names are migrated.
RuntimeProvider = LlmProvider
RuntimeModel = LlmModel
RuntimeGlobalProvider = LlmProvider
RuntimeGlobalModel = LlmModel
RuntimeModelDefault = LlmRuntimeDefault
