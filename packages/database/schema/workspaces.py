from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class ProjectWorkspace(Base):
    __tablename__ = "project_workspaces"
    __table_args__ = (
        Index("project_workspaces_company_project_idx", "org_id", "project_id"),
        Index("project_workspaces_project_primary_idx", "project_id", "is_primary"),
        Index(
            "project_workspaces_project_source_type_idx", "project_id", "source_type"
        ),
        Index(
            "project_workspaces_company_shared_key_idx",
            "org_id",
            "shared_workspace_key",
        ),
        UniqueConstraint(
            "project_id",
            "remote_provider",
            "remote_workspace_ref",
            name="project_workspaces_project_remote_ref_idx",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="local_path"
    )
    cwd: Mapped[str | None] = mapped_column(Text)
    repo_url: Mapped[str | None] = mapped_column(Text)
    repo_ref: Mapped[str | None] = mapped_column(Text)
    default_ref: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    setup_command: Mapped[str | None] = mapped_column(Text)
    cleanup_command: Mapped[str | None] = mapped_column(Text)
    remote_provider: Mapped[str | None] = mapped_column(Text)
    remote_workspace_ref: Mapped[str | None] = mapped_column(Text)
    shared_workspace_key: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON().with_variant(JSONB(), "postgresql")
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExecutionWorkspace(Base):
    __tablename__ = "execution_workspaces"
    __table_args__ = (
        Index(
            "execution_workspaces_company_project_status_idx",
            "org_id",
            "project_id",
            "status",
        ),
        Index(
            "execution_workspaces_company_project_workspace_status_idx",
            "org_id",
            "project_workspace_id",
            "status",
        ),
        Index(
            "execution_workspaces_company_source_issue_idx",
            "org_id",
            "source_issue_id",
        ),
        Index(
            "execution_workspaces_company_last_used_idx",
            "org_id",
            "last_used_at",
        ),
        Index(
            "execution_workspaces_company_branch_idx",
            "org_id",
            "branch_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    project_workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project_workspaces.id", ondelete="SET NULL")
    )
    source_issue_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("issues.id", ondelete="SET NULL")
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    cwd: Mapped[str | None] = mapped_column(Text)
    repo_url: Mapped[str | None] = mapped_column(Text)
    base_ref: Mapped[str | None] = mapped_column(Text)
    branch_name: Mapped[str | None] = mapped_column(Text)
    provider_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="local_fs"
    )
    provider_ref: Mapped[str | None] = mapped_column(Text)
    derived_from_execution_workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("execution_workspaces.id", ondelete="SET NULL")
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_eligible_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    cleanup_reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON().with_variant(JSONB(), "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkspaceRuntimeService(Base):
    __tablename__ = "workspace_runtime_services"
    __table_args__ = (
        Index(
            "workspace_runtime_services_company_workspace_status_idx",
            "org_id",
            "project_workspace_id",
            "status",
        ),
        Index(
            "workspace_runtime_services_company_execution_workspace_status_idx",
            "org_id",
            "execution_workspace_id",
            "status",
        ),
        Index(
            "workspace_runtime_services_company_project_status_idx",
            "org_id",
            "project_id",
            "status",
        ),
        Index("workspace_runtime_services_run_idx", "started_by_run_id"),
        Index(
            "workspace_runtime_services_company_updated_idx",
            "org_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL")
    )
    project_workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project_workspaces.id", ondelete="SET NULL")
    )
    execution_workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("execution_workspaces.id", ondelete="SET NULL")
    )
    issue_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("issues.id", ondelete="SET NULL")
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[str | None] = mapped_column(Text)
    service_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    lifecycle: Mapped[str] = mapped_column(Text, nullable=False)
    reuse_key: Mapped[str | None] = mapped_column(Text)
    command: Mapped[str | None] = mapped_column(Text)
    cwd: Mapped[str | None] = mapped_column(Text)
    port: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(Text)
    owner_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL")
    )
    started_by_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("heartbeat_runs.id", ondelete="SET NULL")
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_policy: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    health_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="unknown"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkspaceOperation(Base):
    __tablename__ = "workspace_operations"
    __table_args__ = (
        Index(
            "workspace_operations_company_run_started_idx",
            "org_id",
            "heartbeat_run_id",
            "started_at",
        ),
        Index(
            "workspace_operations_company_workspace_started_idx",
            "org_id",
            "execution_workspace_id",
            "started_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    execution_workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("execution_workspaces.id", ondelete="SET NULL")
    )
    heartbeat_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("heartbeat_runs.id", ondelete="SET NULL")
    )
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[str | None] = mapped_column(Text)
    cwd: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    exit_code: Mapped[int | None] = mapped_column(Integer)
    log_store: Mapped[str | None] = mapped_column(Text)
    log_ref: Mapped[str | None] = mapped_column(Text)
    log_bytes: Mapped[int | None] = mapped_column(BigInteger)
    log_sha256: Mapped[str | None] = mapped_column(Text)
    log_compressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    stdout_excerpt: Mapped[str | None] = mapped_column(Text)
    stderr_excerpt: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON().with_variant(JSONB(), "postgresql")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IssueWorkProduct(Base):
    __tablename__ = "issue_work_products"
    __table_args__ = (
        Index(
            "issue_work_products_company_issue_type_idx",
            "org_id",
            "issue_id",
            "type",
        ),
        Index(
            "issue_work_products_company_execution_workspace_type_idx",
            "org_id",
            "execution_workspace_id",
            "type",
        ),
        Index(
            "issue_work_products_company_provider_external_id_idx",
            "org_id",
            "provider",
            "external_id",
        ),
        Index("issue_work_products_company_updated_idx", "org_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="SET NULL")
    )
    issue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    execution_workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("execution_workspaces.id", ondelete="SET NULL")
    )
    runtime_service_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workspace_runtime_services.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    review_state: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    health_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="unknown"
    )
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON().with_variant(JSONB(), "postgresql")
    )
    created_by_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("heartbeat_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
