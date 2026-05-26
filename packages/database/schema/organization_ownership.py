from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base


class OrganizationOwnership(Base):
    __tablename__ = "organization_ownership"

    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), primary_key=True
    )
    pod_id: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_version: Mapped[int] = mapped_column(nullable=False, default=0)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
