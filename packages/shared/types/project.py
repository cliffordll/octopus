from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from ..constants.project import (
    OrganizationResourceKind,
    PauseReason,
    ProjectResourceAttachmentRole,
    ProjectStatus,
)
from .workspace import ProjectExecutionWorkspacePolicy, ProjectWorkspace


class OrganizationResource(TypedDict):
    id: str
    orgId: str
    name: str
    kind: OrganizationResourceKind
    locator: str
    description: str | None
    metadata: dict[str, Any] | None
    createdAt: str
    updatedAt: str


class ProjectResourceAttachment(TypedDict):
    id: str
    orgId: str
    projectId: str
    resourceId: str
    role: ProjectResourceAttachmentRole
    note: str | None
    sortOrder: int
    resource: OrganizationResource
    createdAt: str
    updatedAt: str


class ProjectGoalRef(TypedDict):
    id: str
    title: str


class ProjectCodebase(TypedDict):
    configured: bool
    scope: str
    workspaceId: str | None
    repoUrl: str | None
    repoRef: str | None
    defaultRef: str | None
    repoName: str | None
    localFolder: str | None
    managedFolder: str
    effectiveLocalFolder: str
    origin: str


class ProjectDetail(TypedDict):
    id: str
    orgId: str
    urlKey: str
    goalId: str | None
    goalIds: list[str]
    goals: list[ProjectGoalRef]
    name: str
    description: str | None
    status: ProjectStatus
    leadAgentId: str | None
    targetDate: str | None
    color: str | None
    pauseReason: PauseReason | None
    pausedAt: str | None
    executionWorkspacePolicy: ProjectExecutionWorkspacePolicy | None
    codebase: ProjectCodebase
    resources: list[ProjectResourceAttachment]
    workspaces: list[ProjectWorkspace]
    primaryWorkspace: ProjectWorkspace | None
    archivedAt: str | None
    createdAt: str
    updatedAt: str


class ProjectResourceAttachmentFields(TypedDict, total=False):
    role: ProjectResourceAttachmentRole
    note: str | None
    sortOrder: int


class ProjectResourceAttachmentInput(ProjectResourceAttachmentFields):
    resourceId: str


class CreateProjectInlineResourceInput(TypedDict):
    name: str
    kind: OrganizationResourceKind
    locator: str
    description: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any] | None]
    role: NotRequired[ProjectResourceAttachmentRole]
    note: NotRequired[str | None]
    sortOrder: NotRequired[int]


class ProjectMutationFields(TypedDict, total=False):
    goalId: str | None
    goalIds: list[str]
    description: str | None
    status: ProjectStatus
    leadAgentId: str | None
    targetDate: str | None
    color: str | None
    executionWorkspacePolicy: dict[str, Any] | None
    resourceAttachments: list[ProjectResourceAttachmentInput]
    newResources: list[CreateProjectInlineResourceInput]
    archivedAt: str | None


class CreateProjectPayload(ProjectMutationFields):
    name: str


class UpdateProjectPayload(ProjectMutationFields, total=False):
    name: str


class ProjectWorkspaceFields(TypedDict, total=False):
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


class CreateProjectWorkspacePayload(ProjectWorkspaceFields):
    name: str


class UpdateProjectWorkspacePayload(ProjectWorkspaceFields, total=False):
    name: str


class UpdateProjectResourceAttachmentPayload(TypedDict, total=False):
    role: ProjectResourceAttachmentRole
    note: str | None
    sortOrder: int
