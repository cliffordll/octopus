from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ..constants.issue import (
    ISSUE_ORIGIN_KINDS,
    ISSUE_PRIORITIES,
    ISSUE_STATUSES,
)
from ..types.issue import (
    CreateIssuePayload,
    ListOrgIssuesQuery,
    UpdateIssuePayload,
)


_NULLABLE_REF_FIELDS = (
    "projectId",
    "goalId",
    "parentId",
    "assigneeAgentId",
    "assigneeUserId",
    "reviewerAgentId",
    "reviewerUserId",
)


def _check_nullable_ref_fields(payload: Mapping[str, Any]) -> None:
    for field in _NULLABLE_REF_FIELDS:
        if field in payload:
            value = payload[field]
            if value is not None and not isinstance(value, str):
                raise ValueError(f"'{field}' must be a string or null")


def _check_status_priority_origin(payload: Mapping[str, Any]) -> None:
    if "status" in payload and payload["status"] not in ISSUE_STATUSES:
        raise ValueError(f"'status' must be one of {list(ISSUE_STATUSES)}")
    if "priority" in payload and payload["priority"] not in ISSUE_PRIORITIES:
        raise ValueError(f"'priority' must be one of {list(ISSUE_PRIORITIES)}")
    if "originKind" in payload and payload["originKind"] not in ISSUE_ORIGIN_KINDS:
        raise ValueError(f"'originKind' must be one of {list(ISSUE_ORIGIN_KINDS)}")


def validate_list_org_issues_query(
    query: Mapping[str, Any],
) -> ListOrgIssuesQuery:
    _check_status_priority_origin(query)
    for field in (
        "assigneeAgentId",
        "assigneeUserId",
        "reviewerAgentId",
        "reviewerUserId",
        "projectId",
        "parentId",
        "originId",
        "q",
    ):
        if field in query and not isinstance(query[field], str):
            raise ValueError(f"'{field}' must be a string")
    return cast(ListOrgIssuesQuery, query)


def validate_create_issue(payload: Mapping[str, Any]) -> CreateIssuePayload:
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("'title' is required and must be a non-empty string")

    if "description" in payload:
        desc = payload["description"]
        if desc is not None and not isinstance(desc, str):
            raise ValueError("'description' must be a string or null")

    _check_status_priority_origin(payload)
    _check_nullable_ref_fields(payload)

    if "originId" in payload:
        origin_id = payload["originId"]
        if origin_id is not None and not isinstance(origin_id, str):
            raise ValueError("'originId' must be a string or null")

    if "requestDepth" in payload:
        depth = payload["requestDepth"]
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise ValueError("'requestDepth' must be a non-negative integer")

    return cast(CreateIssuePayload, payload)


def validate_update_issue(payload: Mapping[str, Any]) -> UpdateIssuePayload:
    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or not title.strip():
            raise ValueError("'title' must be a non-empty string when provided")

    if "description" in payload:
        desc = payload["description"]
        if desc is not None and not isinstance(desc, str):
            raise ValueError("'description' must be a string or null")

    _check_status_priority_origin(payload)
    _check_nullable_ref_fields(payload)

    if "comment" in payload:
        comment = payload["comment"]
        if not isinstance(comment, str) or not comment.strip():
            raise ValueError("'comment' must be a non-empty string when provided")

    if "reopen" in payload and not isinstance(payload["reopen"], bool):
        raise ValueError("'reopen' must be a boolean")

    if "hiddenAt" in payload:
        hidden = payload["hiddenAt"]
        if hidden is not None and not isinstance(hidden, str):
            raise ValueError("'hiddenAt' must be a string or null")

    if "reviewDecision" in payload and not isinstance(payload["reviewDecision"], dict):
        raise ValueError("'reviewDecision' must be an object")

    return cast(UpdateIssuePayload, payload)
