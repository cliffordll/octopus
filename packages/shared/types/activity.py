from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

ActivityActorType = Literal["agent", "user", "system", "board"]


class ActivityEvent(TypedDict):
    id: str
    orgId: str
    actorType: str
    actorId: str
    action: str
    entityType: str
    entityId: str
    agentId: str | None
    runId: str | None
    details: dict[str, Any] | None
    createdAt: str


class CreateActivityPayload(TypedDict):
    actorId: str
    action: str
    entityType: str
    entityId: str
    actorType: NotRequired[ActivityActorType]
    agentId: NotRequired[str | None]
    runId: NotRequired[str | None]
    details: NotRequired[dict[str, Any] | None]


class ActivityQuery(TypedDict, total=False):
    agentId: str
    userId: str
    actorType: str
    actorId: str
    action: str
    entityType: str
    entityId: str
    runId: str | None
    startTime: str
    endTime: str
    limit: int
    offset: int


class IssueRunSummary(TypedDict):
    runId: str
    status: str
    agentId: str
    invocationSource: str
    runPurpose: str
    triggerDetail: str | None
    createdAt: str
    startedAt: str | None
    finishedAt: str | None
    error: str | None
    summary: str | None
    issueId: str
    issueIdentifier: str | None
    issueTitle: str
    projectId: str | None
    goalId: str | None


class RunIssueSummary(TypedDict):
    issueId: str
    identifier: str | None
    title: str
    status: str
    priority: str
