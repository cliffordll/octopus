from typing import Literal

HeartbeatInvocationSource = Literal[
    "timer", "assignment", "review", "on_demand", "automation"
]
WakeupTriggerDetail = Literal["manual", "ping", "callback", "system"]
WakeupRequestStatus = Literal[
    "queued",
    "deferred_issue_execution",
    "deferred_agent_paused",
    "claimed",
    "coalesced",
    "skipped",
    "completed",
    "failed",
    "cancelled",
]
HeartbeatRunStatus = Literal[
    "queued", "running", "succeeded", "failed", "cancelled", "timed_out"
]

HEARTBEAT_INVOCATION_SOURCES: tuple[HeartbeatInvocationSource, ...] = (
    "timer",
    "assignment",
    "review",
    "on_demand",
    "automation",
)
WAKEUP_TRIGGER_DETAILS: tuple[WakeupTriggerDetail, ...] = (
    "manual",
    "ping",
    "callback",
    "system",
)
WAKEUP_REQUEST_STATUSES: tuple[WakeupRequestStatus, ...] = (
    "queued",
    "deferred_issue_execution",
    "deferred_agent_paused",
    "claimed",
    "coalesced",
    "skipped",
    "completed",
    "failed",
    "cancelled",
)
HEARTBEAT_RUN_STATUSES: tuple[HeartbeatRunStatus, ...] = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
)
