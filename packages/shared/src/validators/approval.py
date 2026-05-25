from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ..constants.approval import APPROVAL_STATUSES, APPROVAL_TYPES
from ..types.approval import (
    CreateApprovalPayload,
    ListOrgApprovalsQuery,
    ResolveApprovalPayload,
)


def validate_list_org_approvals_query(
    query: Mapping[str, Any],
) -> ListOrgApprovalsQuery:
    if "status" in query and query["status"] not in APPROVAL_STATUSES:
        raise ValueError(f"'status' must be one of {list(APPROVAL_STATUSES)}")
    return cast(ListOrgApprovalsQuery, query)


def validate_create_approval(payload: Mapping[str, Any]) -> CreateApprovalPayload:
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

    if "issueIds" in payload:
        issue_ids = payload["issueIds"]
        if not isinstance(issue_ids, list) or not all(
            isinstance(item, str) for item in issue_ids
        ):
            raise ValueError("'issueIds' must be a list of strings")

    return cast(CreateApprovalPayload, payload)


def validate_resolve_approval(payload: Mapping[str, Any]) -> ResolveApprovalPayload:
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

    return cast(ResolveApprovalPayload, payload)
