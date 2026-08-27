from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class PrincipalPermissionGrant(Base):
    __tablename__ = "principal_permission_grants"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "principal_type",
            "principal_id",
            "permission_key",
            name="principal_permission_grants_unique_idx",
        ),
        Index(
            "principal_permission_grants_company_permission_idx",
            "org_id",
            "permission_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    principal_type: Mapped[str] = mapped_column(Text, nullable=False)
    principal_id: Mapped[str] = mapped_column(Text, nullable=False)
    permission_key: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    granted_by_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InstanceUserRoleGrant(Base):
    __tablename__ = "instance_user_roles"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "role",
            name="instance_user_roles_user_role_unique_idx",
        ),
        Index("instance_user_roles_role_idx", "role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="instance_admin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
