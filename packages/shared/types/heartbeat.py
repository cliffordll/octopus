from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from packages.shared.constants.heartbeat import (
    HeartbeatInvocationSource,
    HeartbeatRunStatus,
    WakeupTriggerDetail,
)


class WakeAgentPayload(TypedDict, total=False):
    source: HeartbeatInvocationSource
    triggerDetail: WakeupTriggerDetail
    reason: str | None
    payload: dict[str, Any] | None
    contextSnapshot: dict[str, Any] | None
    idempotencyKey: str | None
    forceFreshSession: bool


class HeartbeatRun(TypedDict):
    id: str
    orgId: str
    agentId: str
    invocationSource: HeartbeatInvocationSource
    triggerDetail: WakeupTriggerDetail | None
    status: HeartbeatRunStatus
    startedAt: str | None
    finishedAt: str | None
    error: str | None
    wakeupRequestId: str | None
    exitCode: int | None
    signal: str | None
    usageJson: dict[str, Any] | None
    resultJson: dict[str, Any] | None
    sessionIdBefore: str | None
    sessionIdAfter: str | None
    logStore: str | None
    logRef: str | None
    logBytes: int | None
    logSha256: str | None
    logCompressed: bool
    stdoutExcerpt: str | None
    stderrExcerpt: str | None
    errorCode: str | None
    externalRunId: str | None
    processPid: int | None
    processStartedAt: str | None
    retryOfRunId: str | None
    processLossRetryCount: int
    contextSnapshot: dict[str, Any] | None
    issueId: NotRequired[str | None]
    issueIdentifier: NotRequired[str | None]
    issueTitle: NotRequired[str | None]
    projectId: NotRequired[str | None]
    goalId: NotRequired[str | None]
    createdAt: str
    updatedAt: str


class HeartbeatRunEvent(TypedDict):
    id: int
    orgId: str
    runId: str
    agentId: str
    seq: int
    eventType: str
    stream: str | None
    level: str | None
    color: str | None
    message: str | None
    payload: dict[str, Any] | None
    createdAt: str
