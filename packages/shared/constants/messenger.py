from __future__ import annotations

from typing import Literal

MessengerThreadKind = Literal[
    "chat", "issues", "approvals", "failed-runs", "budget-alerts", "join-requests"
]
MessengerSystemThreadKind = Literal["failed-runs", "budget-alerts", "join-requests"]

MESSENGER_THREAD_KINDS: tuple[MessengerThreadKind, ...] = (
    "chat",
    "issues",
    "approvals",
    "failed-runs",
    "budget-alerts",
    "join-requests",
)
MESSENGER_SYSTEM_THREAD_KINDS: tuple[MessengerSystemThreadKind, ...] = (
    "failed-runs",
    "budget-alerts",
    "join-requests",
)
