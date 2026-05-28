from __future__ import annotations

from typing import Literal

ExecutionWorkspaceStrategyType = Literal[
    "project_primary", "git_worktree", "adapter_managed", "cloud_sandbox"
]
EXECUTION_WORKSPACE_STRATEGY_TYPES: tuple[ExecutionWorkspaceStrategyType, ...] = (
    "project_primary",
    "git_worktree",
    "adapter_managed",
    "cloud_sandbox",
)

ProjectExecutionWorkspaceDefaultMode = Literal[
    "shared_workspace", "isolated_workspace", "operator_branch", "adapter_default"
]
PROJECT_EXECUTION_WORKSPACE_DEFAULT_MODES: tuple[
    ProjectExecutionWorkspaceDefaultMode, ...
] = (
    "shared_workspace",
    "isolated_workspace",
    "operator_branch",
    "adapter_default",
)

ExecutionWorkspaceMode = Literal[
    "inherit",
    "shared_workspace",
    "isolated_workspace",
    "operator_branch",
    "reuse_existing",
    "agent_default",
]
EXECUTION_WORKSPACE_MODES: tuple[ExecutionWorkspaceMode, ...] = (
    "inherit",
    "shared_workspace",
    "isolated_workspace",
    "operator_branch",
    "reuse_existing",
    "agent_default",
)

ExecutionWorkspaceProviderType = Literal[
    "local_fs", "git_worktree", "adapter_managed", "cloud_sandbox"
]
EXECUTION_WORKSPACE_PROVIDER_TYPES: tuple[ExecutionWorkspaceProviderType, ...] = (
    "local_fs",
    "git_worktree",
    "adapter_managed",
    "cloud_sandbox",
)

ExecutionWorkspaceStatus = Literal[
    "active", "idle", "in_review", "archived", "cleanup_failed"
]
EXECUTION_WORKSPACE_STATUSES: tuple[ExecutionWorkspaceStatus, ...] = (
    "active",
    "idle",
    "in_review",
    "archived",
    "cleanup_failed",
)

WorkspaceRuntimeServiceScopeType = Literal[
    "project_workspace", "execution_workspace", "run", "agent"
]
WORKSPACE_RUNTIME_SERVICE_SCOPE_TYPES: tuple[WorkspaceRuntimeServiceScopeType, ...] = (
    "project_workspace",
    "execution_workspace",
    "run",
    "agent",
)

WorkspaceRuntimeServiceStatus = Literal["starting", "running", "stopped", "failed"]
WORKSPACE_RUNTIME_SERVICE_STATUSES: tuple[WorkspaceRuntimeServiceStatus, ...] = (
    "starting",
    "running",
    "stopped",
    "failed",
)

WorkspaceRuntimeServiceLifecycle = Literal["shared", "ephemeral"]
WORKSPACE_RUNTIME_SERVICE_LIFECYCLES: tuple[WorkspaceRuntimeServiceLifecycle, ...] = (
    "shared",
    "ephemeral",
)

WorkspaceRuntimeServiceProvider = Literal["local_process", "adapter_managed"]
WORKSPACE_RUNTIME_SERVICE_PROVIDERS: tuple[WorkspaceRuntimeServiceProvider, ...] = (
    "local_process",
    "adapter_managed",
)

WorkspaceHealthStatus = Literal["unknown", "healthy", "unhealthy"]
WORKSPACE_HEALTH_STATUSES: tuple[WorkspaceHealthStatus, ...] = (
    "unknown",
    "healthy",
    "unhealthy",
)

WorkspaceOperationPhase = Literal[
    "worktree_prepare", "workspace_provision", "workspace_teardown", "worktree_cleanup"
]
WORKSPACE_OPERATION_PHASES: tuple[WorkspaceOperationPhase, ...] = (
    "worktree_prepare",
    "workspace_provision",
    "workspace_teardown",
    "worktree_cleanup",
)

WorkspaceOperationStatus = Literal["running", "succeeded", "failed", "skipped"]
WORKSPACE_OPERATION_STATUSES: tuple[WorkspaceOperationStatus, ...] = (
    "running",
    "succeeded",
    "failed",
    "skipped",
)

IssueWorkProductType = Literal[
    "preview_url",
    "runtime_service",
    "pull_request",
    "branch",
    "commit",
    "artifact",
    "document",
]
ISSUE_WORK_PRODUCT_TYPES: tuple[IssueWorkProductType, ...] = (
    "preview_url",
    "runtime_service",
    "pull_request",
    "branch",
    "commit",
    "artifact",
    "document",
)

IssueWorkProductProvider = Literal["rudder", "github", "vercel", "s3", "custom"]
ISSUE_WORK_PRODUCT_PROVIDERS: tuple[IssueWorkProductProvider, ...] = (
    "rudder",
    "github",
    "vercel",
    "s3",
    "custom",
)

IssueWorkProductStatus = Literal[
    "active",
    "ready_for_review",
    "approved",
    "changes_requested",
    "merged",
    "closed",
    "failed",
    "archived",
    "draft",
]
ISSUE_WORK_PRODUCT_STATUSES: tuple[IssueWorkProductStatus, ...] = (
    "active",
    "ready_for_review",
    "approved",
    "changes_requested",
    "merged",
    "closed",
    "failed",
    "archived",
    "draft",
)

IssueWorkProductReviewState = Literal[
    "none", "needs_board_review", "approved", "changes_requested"
]
ISSUE_WORK_PRODUCT_REVIEW_STATES: tuple[IssueWorkProductReviewState, ...] = (
    "none",
    "needs_board_review",
    "approved",
    "changes_requested",
)
