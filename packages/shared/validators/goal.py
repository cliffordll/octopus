from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
import uuid

from ..constants.goal import (
    DEFAULT_GOAL_LEVEL,
    DEFAULT_GOAL_STATUS,
    GOAL_LEVELS,
    GOAL_STATUSES,
)
from ..types.goal import CreateGoalPayload, UpdateGoalPayload

_FIELDS = {"title", "description", "level", "status", "parentId", "ownerAgentId"}


def _validate_fields(
    payload: Mapping[str, Any], *, require_title: bool
) -> dict[str, Any]:
    for field in payload:
        if field not in _FIELDS:
            raise ValueError(f"Unsupported field: '{field}'")
    if require_title or "title" in payload:
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("'title' is required and must be a non-empty string")
    if "description" in payload and payload["description"] is not None:
        if not isinstance(payload["description"], str):
            raise ValueError("'description' must be a string or null")
    if "level" in payload and payload["level"] not in GOAL_LEVELS:
        raise ValueError(f"'level' must be one of {list(GOAL_LEVELS)}")
    if "status" in payload and payload["status"] not in GOAL_STATUSES:
        raise ValueError(f"'status' must be one of {list(GOAL_STATUSES)}")
    for field in ("parentId", "ownerAgentId"):
        if field in payload and payload[field] is not None:
            try:
                uuid.UUID(str(payload[field]))
            except ValueError as exc:
                raise ValueError(f"'{field}' must be a UUID or null") from exc
    return dict(payload)


def validate_create_goal(payload: Mapping[str, Any]) -> CreateGoalPayload:
    result = _validate_fields(payload, require_title=True)
    result.setdefault("level", DEFAULT_GOAL_LEVEL)
    result.setdefault("status", DEFAULT_GOAL_STATUS)
    return cast(CreateGoalPayload, result)


def validate_update_goal(payload: Mapping[str, Any]) -> UpdateGoalPayload:
    return cast(UpdateGoalPayload, _validate_fields(payload, require_title=False))
