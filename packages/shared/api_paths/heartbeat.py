AGENT_WAKEUP_PATH = "/api/agents/{id}/wakeup"
AGENT_HEARTBEAT_INVOKE_PATH = "/api/agents/{id}/heartbeat/invoke"
ORG_HEARTBEAT_RUNS_PATH = "/api/orgs/{orgId}/heartbeat-runs"
ISSUE_HEARTBEAT_RUNS_PATH = "/api/issues/{issueId}/heartbeat-runs"
HEARTBEAT_RUN_PATH = "/api/heartbeat-runs/{runId}"
HEARTBEAT_RUN_EVENTS_PATH = "/api/heartbeat-runs/{runId}/events"
HEARTBEAT_RUN_LOG_PATH = "/api/heartbeat-runs/{runId}/log"
HEARTBEAT_RUN_STREAM_PATH = "/api/heartbeat-runs/{runId}/stream"
HEARTBEAT_RUN_WORKSPACE_OPERATIONS_PATH = (
    "/api/heartbeat-runs/{runId}/workspace-operations"
)
HEARTBEAT_RUN_CANCEL_PATH = "/api/heartbeat-runs/{runId}/cancel"
HEARTBEAT_RUN_RETRY_PATH = "/api/heartbeat-runs/{runId}/retry"
