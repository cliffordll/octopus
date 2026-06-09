from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class BudgetPolicy(Base):
    __tablename__ = "budget_policies"
    __table_args__ = (
        Index(
            "budget_policies_company_scope_active_idx",
            "org_id",
            "scope_type",
            "scope_id",
            "is_active",
        ),
        Index(
            "budget_policies_company_window_idx",
            "org_id",
            "window_kind",
            "metric",
        ),
        Index(
            "budget_policies_company_scope_metric_unique_idx",
            "org_id",
            "scope_type",
            "scope_id",
            "metric",
            "window_kind",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False, default="billed_cents")
    window_kind: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warn_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    hard_stop_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    notify_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[str | None] = mapped_column(Text)
    updated_by_user_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BudgetIncident(Base):
    __tablename__ = "budget_incidents"
    __table_args__ = (
        Index("budget_incidents_company_status_idx", "org_id", "status"),
        Index(
            "budget_incidents_company_scope_idx",
            "org_id",
            "scope_type",
            "scope_id",
            "status",
        ),
        Index(
            "budget_incidents_policy_window_threshold_idx",
            "policy_id",
            "window_start",
            "threshold_type",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    policy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("budget_policies.id"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str] = mapped_column(String(36), nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    window_kind: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    threshold_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_observed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    approval_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("approvals.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
