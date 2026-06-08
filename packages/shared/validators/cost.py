from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from packages.shared.types.cost import CostQuery, CreateCostEventPayload

_CREATE_FIELDS = {
    "agentId",
    "projectId",
    "sourceType",
    "sourceId",
    "runtimeType",
    "provider",
    "model",
    "biller",
    "costCents",
    "costUsd",
    "inputTokens",
    "outputTokens",
    "totalTokens",
    "usage",
    "metadata",
    "occurredAt",
}
_QUERY_FIELDS = {
    "agentId",
    "projectId",
    "provider",
    "biller",
    "model",
    "startTime",
    "endTime",
    "limit",
}


def validate_create_cost_event(payload: dict[str, Any]) -> CreateCostEventPayload:
    unknown = set(payload) - _CREATE_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

    result: dict[str, Any] = {}
    for field in (
        "agentId",
        "projectId",
        "sourceType",
        "sourceId",
        "runtimeType",
        "provider",
        "model",
        "biller",
    ):
        value = _optional_string(payload.get(field), field)
        if value is not None:
            result[field] = value
    if "costCents" in payload:
        result["costCents"] = _nonnegative_int(payload["costCents"], "costCents")
    elif "costUsd" in payload:
        cost_usd = _nonnegative_float(payload["costUsd"], "costUsd")
        result["costUsd"] = cost_usd
        result["costCents"] = int(round(cost_usd * 100))
    else:
        raise ValueError("costCents or costUsd is required")
    for field in ("inputTokens", "outputTokens", "totalTokens"):
        if field in payload:
            result[field] = _optional_nonnegative_int(payload[field], field)
    for field in ("usage", "metadata"):
        if field in payload:
            result[field] = _optional_record(payload[field], field)
    occurred_at = _optional_string(payload.get("occurredAt"), "occurredAt")
    if occurred_at is not None:
        _parse_datetime(occurred_at, "occurredAt")
        result["occurredAt"] = occurred_at
    return cast(CreateCostEventPayload, result)


def validate_cost_query(params: dict[str, Any]) -> CostQuery:
    unknown = set(params) - _QUERY_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    result: dict[str, Any] = {}
    for field in ("agentId", "projectId", "provider", "biller", "model"):
        value = _optional_string(params.get(field), field)
        if value is not None:
            result[field] = value
    for field in ("startTime", "endTime"):
        value = _optional_string(params.get(field), field)
        if value is not None:
            _parse_datetime(value, field)
            result[field] = value
    if "limit" in params:
        result["limit"] = _int_between(params["limit"], "limit", 1, 500)
    return cast(CostQuery, result)


def parse_cost_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value, "datetime")


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    return value or None


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _optional_nonnegative_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value, field)


def _nonnegative_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError(f"{field} must be a non-negative number")
    return float(value)


def _optional_record(value: Any, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object or null")
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
