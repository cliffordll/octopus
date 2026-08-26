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

DelegationCloseoutPolicyMode = Literal[
    "child_outputs_are_final",
    "parent_output_required",
]

DELEGATION_CLOSEOUT_POLICY_MODES: tuple[DelegationCloseoutPolicyMode, ...] = (
    "child_outputs_are_final",
    "parent_output_required",
)
