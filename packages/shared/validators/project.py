from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import re
from typing import Any, cast
import uuid

from ..constants.project import (
    ORGANIZATION_RESOURCE_KINDS,
    PROJECT_COLORS,
    PROJECT_RESOURCE_ATTACHMENT_ROLES,
    PROJECT_STATUSES,
)
from ..types.project import (
    CreateProjectInlineResourceInput,
    CreateProjectPayload,
    ProjectResourceAttachmentInput,
    UpdateProjectPayload,
    UpdateProjectResourceAttachmentPayload,
)

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_PROJECT_FIELDS = {
    "name",
    "goalId",
    "goalIds",
    "description",
    "status",
    "leadAgentId",
    "targetDate",
    "color",
    "executionWorkspacePolicy",
    "resourceAttachments",
    "newResources",
    "archivedAt",
    "workspace",  # Rudder ignores this legacy create input.
}
_RESOURCE_ATTACHMENT_FIELDS = {"resourceId", "role", "note", "sortOrder"}
_INLINE_RESOURCE_FIELDS = {
    "name",
    "kind",
    "locator",
    "description",
    "metadata",
    "role",
    "note",
    "sortOrder",
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


def _validate_sort_order(payload: Mapping[str, Any]) -> None:
    if "sortOrder" in payload:
        value = payload["sortOrder"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("'sortOrder' must be a non-negative integer")


def validate_project_resource_attachment_input(
    payload: Mapping[str, Any],
) -> ProjectResourceAttachmentInput:
    _reject_unknown_fields(payload, allowed_fields=_RESOURCE_ATTACHMENT_FIELDS)
    resource_id = payload.get("resourceId")
    try:
        uuid.UUID(str(resource_id))
    except ValueError as exc:
        raise ValueError("'resourceId' must be a UUID") from exc
    if "role" in payload and payload["role"] not in PROJECT_RESOURCE_ATTACHMENT_ROLES:
        raise ValueError(
            f"'role' must be one of {list(PROJECT_RESOURCE_ATTACHMENT_ROLES)}"
        )
    _nullable_string(payload, "note")
    _validate_sort_order(payload)
    return cast(ProjectResourceAttachmentInput, dict(payload))


def validate_update_project_resource_attachment(
    payload: Mapping[str, Any],
) -> UpdateProjectResourceAttachmentPayload:
    _reject_unknown_fields(payload, allowed_fields={"role", "note", "sortOrder"})
    if "role" in payload and payload["role"] not in PROJECT_RESOURCE_ATTACHMENT_ROLES:
        raise ValueError(
            f"'role' must be one of {list(PROJECT_RESOURCE_ATTACHMENT_ROLES)}"
        )
    _nullable_string(payload, "note")
    _validate_sort_order(payload)
    return cast(UpdateProjectResourceAttachmentPayload, dict(payload))


def _validate_inline_resource(
    payload: Mapping[str, Any],
) -> CreateProjectInlineResourceInput:
    _reject_unknown_fields(payload, allowed_fields=_INLINE_RESOURCE_FIELDS)
    for field in ("name", "locator"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{field}' is required and must be a non-empty string")
    if payload.get("kind") not in ORGANIZATION_RESOURCE_KINDS:
        raise ValueError(
            f"'kind' is required and must be one of {list(ORGANIZATION_RESOURCE_KINDS)}"
        )
    _nullable_string(payload, "description")
    if (
        "metadata" in payload
        and payload["metadata"] is not None
        and not isinstance(payload["metadata"], dict)
    ):
        raise ValueError("'metadata' must be an object or null")
    if "role" in payload and payload["role"] not in PROJECT_RESOURCE_ATTACHMENT_ROLES:
        raise ValueError(
            f"'role' must be one of {list(PROJECT_RESOURCE_ATTACHMENT_ROLES)}"
        )
    _nullable_string(payload, "note")
    _validate_sort_order(payload)
    return cast(CreateProjectInlineResourceInput, dict(payload))


def _validate_project_fields(
    payload: Mapping[str, Any], *, require_name: bool
) -> dict[str, Any]:
    _reject_unknown_fields(payload, allowed_fields=_PROJECT_FIELDS)
    result = {key: value for key, value in payload.items() if key != "workspace"}
    if require_name:
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("'name' is required and must be a non-empty string")
    elif "name" in payload and (
        not isinstance(payload["name"], str) or not payload["name"].strip()
    ):
        raise ValueError("'name' must be a non-empty string when provided")
    for field in ("description", "leadAgentId", "targetDate", "archivedAt"):
        _nullable_string(payload, field)
    if "goalId" in payload and payload["goalId"] is not None:
        try:
            uuid.UUID(str(payload["goalId"]))
        except ValueError as exc:
            raise ValueError("'goalId' must be a UUID or null") from exc
    if "goalIds" in payload:
        goal_ids = payload["goalIds"]
        if not isinstance(goal_ids, list):
            raise ValueError("'goalIds' must be an array")
        for goal_id in goal_ids:
            try:
                uuid.UUID(str(goal_id))
            except ValueError as exc:
                raise ValueError("'goalIds' entries must be UUIDs") from exc
    if "status" in payload and payload["status"] not in PROJECT_STATUSES:
        raise ValueError(f"'status' must be one of {list(PROJECT_STATUSES)}")
    if "color" in payload and payload["color"] is not None:
        color = payload["color"]
        if not isinstance(color, str) or (
            not _HEX_COLOR.fullmatch(color) and color not in PROJECT_COLORS
        ):
            raise ValueError(
                "'color' must be a 6-digit hex value or supported gradient"
            )
    if (
        "executionWorkspacePolicy" in payload
        and payload["executionWorkspacePolicy"] is not None
    ):
        if not isinstance(payload["executionWorkspacePolicy"], dict):
            raise ValueError("'executionWorkspacePolicy' must be an object or null")
    if "archivedAt" in payload and payload["archivedAt"] is not None:
        try:
            datetime.fromisoformat(str(payload["archivedAt"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("'archivedAt' must be an ISO datetime or null") from exc
    if "resourceAttachments" in payload:
        attachments = payload["resourceAttachments"]
        if not isinstance(attachments, list):
            raise ValueError("'resourceAttachments' must be an array")
        result["resourceAttachments"] = [
            validate_project_resource_attachment_input(item)
            for item in attachments
            if isinstance(item, Mapping)
        ]
        if len(result["resourceAttachments"]) != len(attachments):
            raise ValueError("'resourceAttachments' entries must be objects")
    if "newResources" in payload:
        resources = payload["newResources"]
        if not isinstance(resources, list):
            raise ValueError("'newResources' must be an array")
        result["newResources"] = [
            _validate_inline_resource(item)
            for item in resources
            if isinstance(item, Mapping)
        ]
        if len(result["newResources"]) != len(resources):
            raise ValueError("'newResources' entries must be objects")
    return result


def validate_create_project(payload: Mapping[str, Any]) -> CreateProjectPayload:
    return cast(
        CreateProjectPayload, _validate_project_fields(payload, require_name=True)
    )


def validate_update_project(payload: Mapping[str, Any]) -> UpdateProjectPayload:
    return cast(
        UpdateProjectPayload, _validate_project_fields(payload, require_name=False)
    )
