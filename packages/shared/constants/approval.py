from __future__ import annotations

from typing import Literal

ApprovalType = Literal[
    "hire_agent",
    "approve_ceo_strategy",
    "budget_override_required",
    "chat_issue_creation",
    "chat_operation",
]

APPROVAL_TYPES: tuple[ApprovalType, ...] = (
    "hire_agent",
    "approve_ceo_strategy",
    "budget_override_required",
    "chat_issue_creation",
    "chat_operation",
)

ApprovalStatus = Literal[
    "pending",
    "revision_requested",
    "approved",
    "rejected",
    "cancelled",
]

APPROVAL_STATUSES: tuple[ApprovalStatus, ...] = (
    "pending",
    "revision_requested",
    "approved",
    "rejected",
    "cancelled",
)

DEFAULT_APPROVAL_STATUS: ApprovalStatus = "pending"
