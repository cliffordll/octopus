from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ._base import Base, new_uuid


class OrganizationSkill(Base):
    __tablename__ = "organization_skills"
    __table_args__ = (
        UniqueConstraint("org_id", "key", name="organization_skills_org_key_idx"),
        Index("organization_skills_org_name_idx", "org_id", "name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="local_path")
    source_locator: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    trust_level: Mapped[str] = mapped_column(
        Text, nullable=False, default="markdown_only"
    )
    compatibility: Mapped[str] = mapped_column(
        Text, nullable=False, default="compatible"
    )
    file_inventory: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
