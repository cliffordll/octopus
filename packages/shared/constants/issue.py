from __future__ import annotations

from typing import Literal

IssueStatus = Literal[
    "backlog",
    "todo",
    "in_progress",
    "in_review",
    "done",
    "blocked",
    "cancelled",
]

ISSUE_STATUSES: tuple[IssueStatus, ...] = (
    "backlog",
    "todo",
    "in_progress",
    "in_review",
    "done",
    "blocked",
    "cancelled",
)

DEFAULT_ISSUE_STATUS: IssueStatus = "backlog"

IssuePriority = Literal["critical", "high", "medium", "low"]

ISSUE_PRIORITIES: tuple[IssuePriority, ...] = (
    "critical",
    "high",
    "medium",
    "low",
)

DEFAULT_ISSUE_PRIORITY: IssuePriority = "medium"

IssueOriginKind = Literal["manual", "automation_execution", "delegation"]

ISSUE_ORIGIN_KINDS: tuple[IssueOriginKind, ...] = (
    "manual",
    "automation_execution",
    "delegation",
)

DEFAULT_ISSUE_ORIGIN_KIND: IssueOriginKind = "manual"

DelegationCloseoutMode = Literal["parent_summary", "child_outputs"]

DELEGATION_CLOSEOUT_MODES: tuple[DelegationCloseoutMode, ...] = (
    "parent_summary",
    "child_outputs",
)

DEFAULT_DELEGATION_CLOSEOUT_MODE: DelegationCloseoutMode = "parent_summary"
