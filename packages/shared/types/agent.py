from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from ..constants.agent import AgentRole, AgentRuntimeType, AgentStatus, PauseReason


class AgentPermissions(TypedDict):
    canCreateAgents: bool


class Agent(TypedDict):
    id: str
    orgId: str
    name: str
    urlKey: str
    role: AgentRole
    title: str | None
    icon: str | None
    status: AgentStatus
    reportsTo: str | None
    capabilities: str | None
    desiredSkills: list[str]
    agentRuntimeType: AgentRuntimeType
    agentRuntimeConfig: dict[str, Any]
    runtimeConfig: dict[str, Any]
    budgetMonthlyCents: int
    spentMonthlyCents: int
    pauseReason: PauseReason | None
    pausedAt: str | None
    permissions: AgentPermissions
    lastHeartbeatAt: str | None
    metadata: dict[str, Any] | None
    createdAt: str
    updatedAt: str


class AgentChainOfCommandEntry(TypedDict):
    id: str
    name: str
    role: AgentRole
    title: str | None


class AgentAccessState(TypedDict):
    canAssignTasks: bool
    taskAssignSource: str
    membership: None
    grants: list[dict[str, Any]]


class AgentDetail(Agent):
    chainOfCommand: list[AgentChainOfCommandEntry]
    access: AgentAccessState


class CreateAgentPayload(TypedDict, total=False):
    name: NotRequired[str]
    role: AgentRole
    title: NotRequired[str | None]
    icon: NotRequired[str | None]
    reportsTo: NotRequired[str | None]
    capabilities: NotRequired[str | None]
    desiredSkills: NotRequired[list[str]]
    agentRuntimeType: AgentRuntimeType
    agentRuntimeConfig: dict[str, Any]
    runtimeConfig: dict[str, Any]
    budgetMonthlyCents: int
    permissions: NotRequired[AgentPermissions]
    metadata: NotRequired[dict[str, Any] | None]


class UpdateAgentPayload(TypedDict, total=False):
    name: str
    role: AgentRole
    title: str | None
    icon: str | None
    reportsTo: str | None
    capabilities: str | None
    desiredSkills: list[str]
    agentRuntimeType: AgentRuntimeType
    agentRuntimeConfig: dict[str, Any]
    runtimeConfig: dict[str, Any]
    budgetMonthlyCents: int
    replaceAgentRuntimeConfig: bool
    status: AgentStatus
    spentMonthlyCents: int
    metadata: dict[str, Any] | None


class AgentConfiguration(TypedDict):
    id: str
    orgId: str
    name: str
    role: AgentRole
    title: str | None
    status: AgentStatus
    reportsTo: str | None
    capabilities: str | None
    desiredSkills: list[str]
    agentRuntimeType: AgentRuntimeType
    agentRuntimeConfig: dict[str, Any]
    runtimeConfig: dict[str, Any]
    permissions: AgentPermissions
    updatedAt: str


class AgentConfigRevision(TypedDict):
    id: str
    orgId: str
    agentId: str
    createdByAgentId: str | None
    createdByUserId: str | None
    source: str
    rolledBackFromRevisionId: str | None
    changedKeys: list[str]
    beforeConfig: dict[str, Any]
    afterConfig: dict[str, Any]
    createdAt: str


class AgentRuntimeState(TypedDict):
    agentId: str
    orgId: str
    agentRuntimeType: str
    sessionId: str | None
    stateJson: dict[str, Any]
    lastRunId: str | None
    lastRunStatus: str | None
    totalInputTokens: int
    totalOutputTokens: int
    totalCachedInputTokens: int
    totalCostCents: int
    lastError: str | None
    createdAt: str
    updatedAt: str
    sessionDisplayId: str | None
    sessionParamsJson: dict[str, Any] | None


class AgentTaskSession(TypedDict):
    id: str
    orgId: str
    agentId: str
    agentRuntimeType: str
    taskKey: str
    sessionParamsJson: dict[str, Any] | None
    sessionDisplayId: str | None
    lastRunId: str | None
    lastError: str | None
    createdAt: str
    updatedAt: str


class ResetAgentSessionPayload(TypedDict, total=False):
    taskKey: str | None


class ResetAgentSessionResult(AgentRuntimeState):
    clearedTaskSessions: int


class AgentRuntimeModel(TypedDict):
    id: str
    label: str


class AgentRuntimeEnvironmentCheck(TypedDict, total=False):
    id: str
    label: str
    status: str
    message: str
    hint: str | None


class AgentRuntimeEnvironmentTestResult(TypedDict):
    agentRuntimeType: str
    status: str
    checks: list[AgentRuntimeEnvironmentCheck]


class AgentSkillSnapshot(TypedDict):
    agentRuntimeType: str
    supported: bool
    mode: str
    desiredSkills: list[str]
    entries: list[dict[str, Any]]
    warnings: list[str]


class AgentSkillAnalytics(TypedDict):
    agentId: str
    orgId: str
    windowDays: int
    startDate: str
    endDate: str
    totalCount: int
    totalRunsWithSkills: int
    evidenceCounts: dict[str, int]
    skills: list[dict[str, Any]]
    days: list[dict[str, Any]]


class AgentInstructionsFileSummary(TypedDict):
    path: str
    size: int
    language: str
    markdown: bool
    isEntryFile: bool
    editable: bool
    deprecated: bool
    virtual: bool


class AgentInstructionsFileDetail(AgentInstructionsFileSummary):
    content: str


class AgentInstructionsBundle(TypedDict):
    agentId: str
    orgId: str
    mode: str | None
    rootPath: str | None
    managedRootPath: str
    entryFile: str
    resolvedEntryPath: str | None
    editable: bool
    warnings: list[str]
    legacyPromptTemplateActive: bool
    legacyBootstrapPromptTemplateActive: bool
    files: list[AgentInstructionsFileSummary]


class AgentInstructionsPathResult(TypedDict):
    agentId: str
    agentRuntimeType: str
    agentRuntimeConfigKey: str
    path: str | None


class ProviderQuotaResult(TypedDict, total=False):
    provider: str
    source: str | None
    ok: bool
    error: str
    windows: list[dict[str, Any]]


class RuntimeAdapterMetadata(TypedDict):
    type: str
    capabilities: dict[str, bool]
    supportsLocalAgentJwt: bool
    agentConfigurationDoc: str | None
