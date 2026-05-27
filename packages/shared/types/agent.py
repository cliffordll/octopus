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
