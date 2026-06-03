from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NotRequired, TypedDict, cast

from ..constants.workspace import (
    ISSUE_WORK_PRODUCT_REVIEW_STATES,
    ISSUE_WORK_PRODUCT_STATUSES,
    ISSUE_WORK_PRODUCT_TYPES,
    WORKSPACE_HEALTH_STATUSES,
)


class CreateIssueWorkProductPayload(TypedDict):
    projectId: NotRequired[str | None]
    executionWorkspaceId: NotRequired[str | None]
    runtimeServiceId: NotRequired[str | None]
    type: str
    provider: str
    externalId: NotRequired[str | None]
    title: str
    url: NotRequired[str | None]
    status: NotRequired[str]
    reviewState: NotRequired[str]
    isPrimary: NotRequired[bool]
    healthStatus: NotRequired[str]
    summary: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any] | None]
    createdByRunId: NotRequired[str | None]


class UpdateIssueWorkProductPayload(TypedDict, total=False):
    projectId: str | None
    executionWorkspaceId: str | None
    runtimeServiceId: str | None
    type: str
    provider: str
    externalId: str | None
    title: str
    url: str | None
    status: str
    reviewState: str
    isPrimary: bool
    healthStatus: str
    summary: str | None
    metadata: dict[str, Any] | None
    createdByRunId: str | None


_FIELDS = {
    "projectId",
    "executionWorkspaceId",
    "runtimeServiceId",
    "type",
    "provider",
    "externalId",
    "title",
    "url",
    "status",
    "reviewState",
    "isPrimary",
    "healthStatus",
    "summary",
    "metadata",
    "createdByRunId",
}


def _reject_unknown(payload: Mapping[str, Any]) -> None:
    for field in payload:
        if field not in _FIELDS:
            raise ValueError(f"Unsupported field: '{field}'")


def _check_nullable_string(payload: Mapping[str, Any], field: str) -> None:
    if field in payload:
        value = payload[field]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"'{field}' must be a string or null")


def _validate_common(payload: Mapping[str, Any], *, partial: bool) -> None:
    _reject_unknown(payload)
    for field in (
        "projectId",
        "executionWorkspaceId",
        "runtimeServiceId",
        "externalId",
        "url",
        "summary",
        "createdByRunId",
    ):
        _check_nullable_string(payload, field)
    if (not partial or "type" in payload) and payload.get(
        "type"
    ) not in ISSUE_WORK_PRODUCT_TYPES:
        raise ValueError(f"'type' must be one of {list(ISSUE_WORK_PRODUCT_TYPES)}")
    if not partial or "provider" in payload:
        provider = payload.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("'provider' is required and must be a non-empty string")
    if not partial or "title" in payload:
        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("'title' is required and must be a non-empty string")
    if "status" in payload and payload["status"] not in ISSUE_WORK_PRODUCT_STATUSES:
        raise ValueError(f"'status' must be one of {list(ISSUE_WORK_PRODUCT_STATUSES)}")
    if (
        "reviewState" in payload
        and payload["reviewState"] not in ISSUE_WORK_PRODUCT_REVIEW_STATES
    ):
        raise ValueError(
            f"'reviewState' must be one of {list(ISSUE_WORK_PRODUCT_REVIEW_STATES)}"
        )
    if (
        "healthStatus" in payload
        and payload["healthStatus"] not in WORKSPACE_HEALTH_STATUSES
    ):
        raise ValueError(
            f"'healthStatus' must be one of {list(WORKSPACE_HEALTH_STATUSES)}"
        )
    if "isPrimary" in payload and not isinstance(payload["isPrimary"], bool):
        raise ValueError("'isPrimary' must be a boolean")
    if "metadata" in payload:
        metadata = payload["metadata"]
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("'metadata' must be an object or null")


def validate_create_issue_work_product(
    payload: Mapping[str, Any],
) -> CreateIssueWorkProductPayload:
    _validate_common(payload, partial=False)
    result = dict(payload)
    result.setdefault("status", "active")
    result.setdefault("reviewState", "none")
    result.setdefault("isPrimary", False)
    result.setdefault("healthStatus", "unknown")
    return cast(CreateIssueWorkProductPayload, result)


def validate_update_issue_work_product(
    payload: Mapping[str, Any],
) -> UpdateIssueWorkProductPayload:
    _validate_common(payload, partial=True)
    return cast(UpdateIssueWorkProductPayload, payload)
