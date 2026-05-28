from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from packages.shared.constants.workspace import EXECUTION_WORKSPACE_STATUSES
from packages.shared.types.workspace import UpdateExecutionWorkspacePayload

_UPDATE_EXECUTION_WORKSPACE_FIELDS = {
    "status",
    "cleanupEligibleAt",
    "cleanupReason",
    "metadata",
}


def _reject_unknown_fields(
    payload: Mapping[str, Any], *, allowed_fields: set[str]
) -> None:
    for field in payload:
        if field not in allowed_fields:
            raise ValueError(f"Unsupported field: '{field}'")


def _nullable_string(payload: Mapping[str, Any], field: str) -> None:
    if (
        field in payload
        and payload[field] is not None
        and not isinstance(payload[field], str)
    ):
        raise ValueError(f"'{field}' must be a string or null")


def _nullable_datetime(payload: Mapping[str, Any], field: str) -> None:
    if field not in payload or payload[field] is None:
        return
    if not isinstance(payload[field], str):
        raise ValueError(f"'{field}' must be an ISO datetime or null")
    try:
        datetime.fromisoformat(payload[field].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"'{field}' must be an ISO datetime or null") from exc


def validate_update_execution_workspace(
    payload: Mapping[str, Any],
) -> UpdateExecutionWorkspacePayload:
    _reject_unknown_fields(payload, allowed_fields=_UPDATE_EXECUTION_WORKSPACE_FIELDS)
    if "status" in payload and payload["status"] not in EXECUTION_WORKSPACE_STATUSES:
        raise ValueError(
            f"'status' must be one of {list(EXECUTION_WORKSPACE_STATUSES)}"
        )
    _nullable_datetime(payload, "cleanupEligibleAt")
    _nullable_string(payload, "cleanupReason")
    if (
        "metadata" in payload
        and payload["metadata"] is not None
        and not isinstance(payload["metadata"], dict)
    ):
        raise ValueError("'metadata' must be an object or null")
    return cast(UpdateExecutionWorkspacePayload, dict(payload))
