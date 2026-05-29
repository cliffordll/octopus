from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ..constants.approval import APPROVAL_STATUSES, APPROVAL_TYPES
from ..types.approval import (
    CreateApprovalPayload,
    ListOrgApprovalsQuery,
    RequestApprovalRevisionPayload,
    ResolveApprovalPayload,
    ResubmitApprovalPayload,
)

_CREATE_APPROVAL_FIELDS = {
    "type",
    "payload",
    "requestedByAgentId",
    "issueIds",
}

_RESOLVE_APPROVAL_FIELDS = {
    "decisionNote",
    "decidedByUserId",
    "payload",
}

_RESUBMIT_APPROVAL_FIELDS = {
    "payload",
    "issueIds",
}


def _reject_unknown_fields(
    payload: Mapping[str, Any], *, allowed_fields: set[str]
) -> None:
    for field in payload:
        if field not in allowed_fields:
            raise ValueError(f"Unsupported field: '{field}'")


def _validate_issue_ids(payload: Mapping[str, Any]) -> None:
    if "issueIds" not in payload:
        return
    issue_ids = payload["issueIds"]
    if not isinstance(issue_ids, list) or not all(
        isinstance(item, str) for item in issue_ids
    ):
        raise ValueError("'issueIds' must be a list of strings")


def validate_list_org_approvals_query(
    query: Mapping[str, Any],
) -> ListOrgApprovalsQuery:
    if "status" in query and query["status"] not in APPROVAL_STATUSES:
        raise ValueError(f"'status' must be one of {list(APPROVAL_STATUSES)}")
    return cast(ListOrgApprovalsQuery, query)


def validate_create_approval(payload: Mapping[str, Any]) -> CreateApprovalPayload:
    _reject_unknown_fields(payload, allowed_fields=_CREATE_APPROVAL_FIELDS)
    approval_type = payload.get("type")
    if approval_type not in APPROVAL_TYPES:
        raise ValueError(
            f"'type' is required and must be one of {list(APPROVAL_TYPES)}"
        )

    if "payload" not in payload or not isinstance(payload["payload"], dict):
        raise ValueError("'payload' is required and must be an object")

    if "requestedByAgentId" in payload:
        agent_id = payload["requestedByAgentId"]
        if agent_id is not None and not isinstance(agent_id, str):
            raise ValueError("'requestedByAgentId' must be a string or null")

    _validate_issue_ids(payload)

    return cast(CreateApprovalPayload, payload)


def validate_resolve_approval(payload: Mapping[str, Any]) -> ResolveApprovalPayload:
    _reject_unknown_fields(payload, allowed_fields=_RESOLVE_APPROVAL_FIELDS)
    if "decisionNote" in payload:
        note = payload["decisionNote"]
        if not isinstance(note, str):
            raise ValueError("'decisionNote' must be a string")

    if "decidedByUserId" in payload:
        user_id = payload["decidedByUserId"]
        if not isinstance(user_id, str):
            raise ValueError("'decidedByUserId' must be a string")

    if "payload" in payload and not isinstance(payload["payload"], dict):
        raise ValueError("'payload' must be an object")

    # Mirror upstream `resolveApprovalSchema.decidedByUserId.default("board")` in
    # `packages/shared/src/validators/approval.ts:15`.
    result = dict(payload)
    result.setdefault("decidedByUserId", "board")
    return cast(ResolveApprovalPayload, result)


def validate_request_approval_revision(
    payload: Mapping[str, Any],
) -> RequestApprovalRevisionPayload:
    # Mirror upstream `requestApprovalRevisionSchema.decidedByUserId.default("board")`
    # in `packages/shared/src/validators/approval.ts:23`.
    result = validate_resolve_approval(payload)
    return cast(RequestApprovalRevisionPayload, result)


def validate_resubmit_approval(payload: Mapping[str, Any]) -> ResubmitApprovalPayload:
    _reject_unknown_fields(payload, allowed_fields=_RESUBMIT_APPROVAL_FIELDS)
    if "payload" in payload and not isinstance(payload["payload"], dict):
        raise ValueError("'payload' must be an object")
    _validate_issue_ids(payload)
    return cast(ResubmitApprovalPayload, payload)
