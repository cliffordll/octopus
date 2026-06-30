from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from packages.shared.constants.workspace import (
    ExecutionWorkspaceMode,
    ExecutionWorkspaceProviderType,
    ExecutionWorkspaceStatus,
    ExecutionWorkspaceStrategyType,
    IssueWorkProductProvider,
    IssueWorkProductReviewState,
    IssueWorkProductStatus,
    IssueWorkProductType,
    ProjectExecutionWorkspaceDefaultMode,
    WorkspaceHealthStatus,
    WorkspaceOperationPhase,
    WorkspaceOperationStatus,
    WorkspaceRuntimeServiceLifecycle,
    WorkspaceRuntimeServiceProvider,
    WorkspaceRuntimeServiceScopeType,
    WorkspaceRuntimeServiceStatus,
)


class ExecutionWorkspaceStrategy(TypedDict, total=False):
    type: ExecutionWorkspaceStrategyType
    mode: str | None
    baseRef: str | None
    branchTemplate: str | None
    operatorBranch: str | None
    worktreeParentDir: str | None
    provisionCommand: str | None
    teardownCommand: str | None


class ProjectExecutionWorkspacePolicy(TypedDict, total=False):
    enabled: bool
    defaultMode: ProjectExecutionWorkspaceDefaultMode
    allowIssueOverride: bool
    defaultProjectWorkspaceId: str | None
    workspaceStrategy: ExecutionWorkspaceStrategy | None
    workspaceRuntime: dict[str, Any] | None
    branchPolicy: dict[str, Any] | None
    pullRequestPolicy: dict[str, Any] | None
    runtimePolicy: dict[str, Any] | None
    cleanupPolicy: dict[str, Any] | None


class IssueExecutionWorkspaceSettings(TypedDict, total=False):
    mode: ExecutionWorkspaceMode
    workspaceStrategy: ExecutionWorkspaceStrategy | None
    workspaceRuntime: dict[str, Any] | None


class ProjectWorkspace(TypedDict):
    id: str
    orgId: str
    projectId: str
    name: str
    sourceType: str
    cwd: str | None
    repoUrl: str | None
    repoRef: str | None
    defaultRef: str | None
    visibility: str
    setupCommand: str | None
    cleanupCommand: str | None
    remoteProvider: str | None
    remoteWorkspaceRef: str | None
    sharedWorkspaceKey: str | None
    metadata: dict[str, Any] | None
    isPrimary: bool
    runtimeServices: NotRequired[list[WorkspaceRuntimeService]]
    createdAt: str
    updatedAt: str


class ExecutionWorkspace(TypedDict):
    id: str
    orgId: str
    projectId: str
    projectWorkspaceId: str | None
    sourceIssueId: str | None
    mode: str
    strategyType: ExecutionWorkspaceStrategyType
    name: str
    status: ExecutionWorkspaceStatus
    cwd: str | None
    repoUrl: str | None
    baseRef: str | None
    branchName: str | None
    providerType: ExecutionWorkspaceProviderType
    gitWritePolicy: NotRequired[str]
    issueArtifactsDir: NotRequired[str]
    leaseKey: NotRequired[str]
    providerRef: str | None
    derivedFromExecutionWorkspaceId: str | None
    lastUsedAt: str
    openedAt: str
    closedAt: str | None
    cleanupEligibleAt: str | None
    cleanupReason: str | None
    metadata: dict[str, Any] | None
    createdAt: str
    updatedAt: str


class WorkspaceRuntimeService(TypedDict):
    id: str
    orgId: str
    projectId: str | None
    projectWorkspaceId: str | None
    executionWorkspaceId: str | None
    issueId: str | None
    scopeType: WorkspaceRuntimeServiceScopeType
    scopeId: str | None
    serviceName: str
    status: WorkspaceRuntimeServiceStatus
    lifecycle: WorkspaceRuntimeServiceLifecycle
    reuseKey: str | None
    command: str | None
    cwd: str | None
    port: int | None
    url: str | None
    provider: WorkspaceRuntimeServiceProvider
    providerRef: str | None
    ownerAgentId: str | None
    startedByRunId: str | None
    lastUsedAt: str
    startedAt: str
    stoppedAt: str | None
    stopPolicy: dict[str, Any] | None
    healthStatus: WorkspaceHealthStatus
    createdAt: str
    updatedAt: str


class WorkspaceOperation(TypedDict):
    id: str
    orgId: str
    executionWorkspaceId: str | None
    heartbeatRunId: str | None
    phase: WorkspaceOperationPhase
    command: str | None
    cwd: str | None
    status: WorkspaceOperationStatus
    exitCode: int | None
    logStore: str | None
    logRef: str | None
    logBytes: int | None
    logSha256: str | None
    logCompressed: bool
    stdoutExcerpt: str | None
    stderrExcerpt: str | None
    metadata: dict[str, Any] | None
    startedAt: str
    finishedAt: str | None
    createdAt: str
    updatedAt: str


class IssueWorkProduct(TypedDict):
    id: str
    orgId: str
    projectId: str | None
    issueId: str
    executionWorkspaceId: str | None
    runtimeServiceId: str | None
    type: IssueWorkProductType
    provider: IssueWorkProductProvider | str
    externalId: str | None
    title: str
    url: str | None
    assetId: NotRequired[str | None]
    contentPath: NotRequired[str | None]
    status: IssueWorkProductStatus | str
    reviewState: IssueWorkProductReviewState
    isPrimary: bool
    healthStatus: WorkspaceHealthStatus
    summary: str | None
    metadata: dict[str, Any] | None
    createdByRunId: str | None
    createdAt: str
    updatedAt: str


class UpdateExecutionWorkspacePayload(TypedDict, total=False):
    status: ExecutionWorkspaceStatus
    cleanupEligibleAt: str | None
    cleanupReason: str | None
    metadata: dict[str, Any] | None


class CreateProjectWorkspacePayload(TypedDict):
    name: str
    sourceType: NotRequired[str]
    cwd: NotRequired[str | None]
    repoUrl: NotRequired[str | None]
    repoRef: NotRequired[str | None]
    defaultRef: NotRequired[str | None]
    visibility: NotRequired[str]
    setupCommand: NotRequired[str | None]
    cleanupCommand: NotRequired[str | None]
    remoteProvider: NotRequired[str | None]
    remoteWorkspaceRef: NotRequired[str | None]
    sharedWorkspaceKey: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any] | None]
    isPrimary: NotRequired[bool]
