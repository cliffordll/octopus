from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from ..constants.approval import ApprovalStatus, ApprovalType


class ApprovalListItem(TypedDict):
    id: str
    orgId: str
    type: ApprovalType
    status: ApprovalStatus
    requestedByAgentId: str | None
    requestedByUserId: str | None
    createdAt: str


class ApprovalDetail(ApprovalListItem):
    payload: dict[str, Any]
    decisionNote: str | None
    decidedByUserId: str | None
    decidedAt: str | None
    updatedAt: str


class ListOrgApprovalsQuery(TypedDict, total=False):
    status: ApprovalStatus


class CreateApprovalPayload(TypedDict):
    type: ApprovalType
    payload: dict[str, Any]
    requestedByAgentId: NotRequired[str | None]
    issueIds: NotRequired[list[str]]


class ResolveApprovalPayload(TypedDict, total=False):
    decisionNote: str
    decidedByUserId: str
    payload: dict[str, Any]
