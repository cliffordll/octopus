from __future__ import annotations

from typing import Any, cast

from packages.shared.constants.heartbeat import (
    HEARTBEAT_INVOCATION_SOURCES,
    WAKEUP_TRIGGER_DETAILS,
    HeartbeatInvocationSource,
    WakeupTriggerDetail,
)
from packages.shared.types.heartbeat import WakeAgentPayload

_FIELDS = {
    "source",
    "triggerDetail",
    "reason",
    "payload",
    "idempotencyKey",
    "forceFreshSession",
}


def validate_wake_agent(payload: dict[str, Any]) -> WakeAgentPayload:
    unknown = set(payload) - _FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    source = payload.get("source", "on_demand")
    if source not in HEARTBEAT_INVOCATION_SOURCES:
        raise ValueError("Invalid source")
    result: WakeAgentPayload = {
        "source": cast(HeartbeatInvocationSource, source),
        "forceFreshSession": bool(payload.get("forceFreshSession", False)),
    }
    detail = payload.get("triggerDetail")
    if detail is not None:
        if detail not in WAKEUP_TRIGGER_DETAILS:
            raise ValueError("Invalid triggerDetail")
        result["triggerDetail"] = cast(WakeupTriggerDetail, detail)
    for field in ("reason", "idempotencyKey"):
        value = payload.get(field)
        if field in payload:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} must be a string or null")
            result[field] = value  # type: ignore[literal-required]
    if "payload" in payload:
        data = payload["payload"]
        if data is not None and not isinstance(data, dict):
            raise ValueError("payload must be an object or null")
        result["payload"] = data
    return result
