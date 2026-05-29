from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from ..constants.issue import IssueOriginKind, IssuePriority, IssueStatus
from .workspace import IssueWorkProduct


class IssueListItem(TypedDict):
    id: str
    orgId: str
    identifier: str | None
    title: str
    status: IssueStatus
    priority: IssuePriority
    projectId: str | None
    goalId: str | None
    assigneeAgentId: str | None
    assigneeUserId: str | None
    originKind: IssueOriginKind
    originId: str | None
    updatedAt: str


class IssueDetail(IssueListItem):
    description: str | None
    reviewerAgentId: str | None
    reviewerUserId: str | None
    projectId: str | None
    goalId: str | None
    parentId: str | None
    originKind: IssueOriginKind
    originId: str | None
    issueNumber: int | None
    requestDepth: int
    startedAt: str | None
    completedAt: str | None
    cancelledAt: str | None
    createdAt: str
    workProducts: list[IssueWorkProduct]


class ListOrgIssuesQuery(TypedDict, total=False):
    status: IssueStatus
    assigneeAgentId: str
    assigneeUserId: str
    reviewerAgentId: str
    reviewerUserId: str
    projectId: str
    parentId: str
    originKind: IssueOriginKind
    originId: str
    q: str


class CreateIssuePayload(TypedDict):
    title: str
    description: NotRequired[str | None]
    status: NotRequired[IssueStatus]
    priority: NotRequired[IssuePriority]
    projectId: NotRequired[str | None]
    goalId: NotRequired[str | None]
    parentId: NotRequired[str | None]
    assigneeAgentId: NotRequired[str | None]
    assigneeUserId: NotRequired[str | None]
    reviewerAgentId: NotRequired[str | None]
    reviewerUserId: NotRequired[str | None]
    originKind: NotRequired[IssueOriginKind]
    originId: NotRequired[str | None]
    requestDepth: NotRequired[int]


class UpdateIssuePayload(TypedDict, total=False):
    title: str
    description: str | None
    status: IssueStatus
    priority: IssuePriority
    projectId: str | None
    goalId: str | None
    parentId: str | None
    assigneeAgentId: str | None
    assigneeUserId: str | None
    reviewerAgentId: str | None
    reviewerUserId: str | None
    comment: str
    reopen: bool
    hiddenAt: str | None
    reviewDecision: "RecordIssueReviewDecisionPayload"


IssueReviewDecision = Literal["approve", "request_changes", "blocked", "needs_followup"]


class CreateIssueCommentPayload(TypedDict):
    body: str


class RecordIssueReviewDecisionPayload(TypedDict):
    decision: IssueReviewDecision
    note: NotRequired[str | None]
