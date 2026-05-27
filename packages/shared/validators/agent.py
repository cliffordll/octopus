from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
import uuid

from ..constants.agent import (
    AGENT_ROLES,
    AGENT_RUNTIME_TYPES,
    AGENT_STATUSES,
    DEFAULT_AGENT_ROLE,
    DEFAULT_AGENT_RUNTIME_TYPE,
)
from ..types.agent import (
    CreateAgentPayload,
    ResetAgentSessionPayload,
    UpdateAgentPayload,
)

_CREATE_FIELDS = {
    "name",
    "role",
    "title",
    "icon",
    "reportsTo",
    "capabilities",
    "desiredSkills",
    "agentRuntimeType",
    "agentRuntimeConfig",
    "runtimeConfig",
    "budgetMonthlyCents",
    "permissions",
    "metadata",
}
_UPDATE_FIELDS = (_CREATE_FIELDS - {"permissions"}) | {
    "replaceAgentRuntimeConfig",
    "status",
    "spentMonthlyCents",
}


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: set[str]) -> None:
    for field in payload:
        if field not in allowed:
            raise ValueError(f"Unsupported field: '{field}'")


def _nullable_string(payload: Mapping[str, Any], field: str) -> None:
    if (
        field in payload
        and payload[field] is not None
        and not isinstance(payload[field], str)
    ):
        raise ValueError(f"'{field}' must be a string or null")


def _record(payload: Mapping[str, Any], field: str) -> None:
    if field in payload and not isinstance(payload[field], dict):
        raise ValueError(f"'{field}' must be an object")


def _nonnegative_integer(payload: Mapping[str, Any], field: str) -> None:
    if field in payload:
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"'{field}' must be a non-negative integer")


def _validate_common(payload: Mapping[str, Any]) -> None:
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("'name' must be a non-empty string")
    if "role" in payload and payload["role"] not in AGENT_ROLES:
        raise ValueError(f"'role' must be one of {list(AGENT_ROLES)}")
    if (
        "agentRuntimeType" in payload
        and payload["agentRuntimeType"] not in AGENT_RUNTIME_TYPES
    ):
        raise ValueError(
            f"'agentRuntimeType' must be one of {list(AGENT_RUNTIME_TYPES)}"
        )
    for field in ("title", "icon", "capabilities"):
        _nullable_string(payload, field)
    if "reportsTo" in payload and payload["reportsTo"] is not None:
        try:
            uuid.UUID(str(payload["reportsTo"]))
        except ValueError as exc:
            raise ValueError("'reportsTo' must be a UUID or null") from exc
    for field in ("agentRuntimeConfig", "runtimeConfig"):
        _record(payload, field)
    _nonnegative_integer(payload, "budgetMonthlyCents")
    if "metadata" in payload and payload["metadata"] is not None:
        _record(payload, "metadata")
    if "desiredSkills" in payload:
        skills = payload["desiredSkills"]
        if not isinstance(skills, list) or any(
            not isinstance(skill, str) or not skill for skill in skills
        ):
            raise ValueError("'desiredSkills' must be an array of non-empty strings")


def validate_create_agent(payload: Mapping[str, Any]) -> CreateAgentPayload:
    _reject_unknown_fields(payload, _CREATE_FIELDS)
    _validate_common(payload)
    result = dict(payload)
    result.setdefault("role", DEFAULT_AGENT_ROLE)
    result.setdefault("agentRuntimeType", DEFAULT_AGENT_RUNTIME_TYPE)
    result.setdefault("agentRuntimeConfig", {})
    result.setdefault("runtimeConfig", {})
    result.setdefault("budgetMonthlyCents", 0)
    return cast(CreateAgentPayload, result)


def validate_update_agent(payload: Mapping[str, Any]) -> UpdateAgentPayload:
    _reject_unknown_fields(payload, _UPDATE_FIELDS)
    _validate_common(payload)
    if "status" in payload and payload["status"] not in AGENT_STATUSES:
        raise ValueError(f"'status' must be one of {list(AGENT_STATUSES)}")
    _nonnegative_integer(payload, "spentMonthlyCents")
    if "replaceAgentRuntimeConfig" in payload and not isinstance(
        payload["replaceAgentRuntimeConfig"], bool
    ):
        raise ValueError("'replaceAgentRuntimeConfig' must be a boolean")
    return cast(UpdateAgentPayload, dict(payload))


def validate_reset_agent_session(
    payload: Mapping[str, Any],
) -> ResetAgentSessionPayload:
    _reject_unknown_fields(payload, {"taskKey"})
    _nullable_string(payload, "taskKey")
    result = dict(payload)
    if isinstance(result.get("taskKey"), str):
        result["taskKey"] = result["taskKey"].strip() or None
    return cast(ResetAgentSessionPayload, result)
