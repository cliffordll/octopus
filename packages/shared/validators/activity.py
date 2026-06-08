from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from packages.shared.types.activity import ActivityQuery, CreateActivityPayload

_CREATE_FIELDS = {
    "actorType",
    "actorId",
    "action",
    "entityType",
    "entityId",
    "agentId",
    "runId",
    "details",
}
_QUERY_FIELDS = {
    "agentId",
    "userId",
    "actorType",
    "actorId",
    "action",
    "entityType",
    "entityId",
    "runId",
    "startTime",
    "endTime",
    "limit",
    "offset",
}
_ACTOR_TYPES = {"agent", "user", "system", "board"}


def validate_create_activity(payload: dict[str, Any]) -> CreateActivityPayload:
    unknown = set(payload) - _CREATE_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    result: dict[str, Any] = {
        "actorType": _optional_enum(payload.get("actorType"), "actorType") or "system",
        "actorId": _required_string(payload.get("actorId"), "actorId"),
        "action": _required_string(payload.get("action"), "action"),
        "entityType": _required_string(payload.get("entityType"), "entityType"),
        "entityId": _required_string(payload.get("entityId"), "entityId"),
    }
    for field in ("agentId", "runId"):
        if field in payload:
            result[field] = _optional_string(payload[field], field)
    if "details" in payload:
        details = payload["details"]
        if details is not None and not isinstance(details, dict):
            raise ValueError("details must be an object or null")
        result["details"] = details
    return cast(CreateActivityPayload, result)


def validate_activity_query(params: dict[str, Any]) -> ActivityQuery:
    unknown = set(params) - _QUERY_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    result: dict[str, Any] = {}
    for field in (
        "agentId",
        "userId",
        "actorId",
        "action",
        "entityType",
        "entityId",
        "runId",
    ):
        value = _optional_string(params.get(field), field)
        if value is not None:
            result[field] = value
    actor_type = _optional_enum(params.get("actorType"), "actorType")
    if actor_type is not None:
        result["actorType"] = actor_type
    for field in ("startTime", "endTime"):
        value = _optional_string(params.get(field), field)
        if value is not None:
            _parse_datetime(value, field)
            result[field] = value
    if "limit" in params:
        result["limit"] = _int_between(params["limit"], "limit", 1, 500)
    if "offset" in params:
        result["offset"] = _int_between(params["offset"], "offset", 0, 100_000)
    return cast(ActivityQuery, result)


def parse_activity_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, "datetime")


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    return value or None


def _optional_enum(value: Any, field: str) -> str | None:
    value = _optional_string(value, field)
    if value is None:
        return None
    if value not in _ACTOR_TYPES:
        raise ValueError(f"Invalid {field}")
    return value


def _int_between(value: Any, field: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _parse_datetime(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO datetime") from exc
