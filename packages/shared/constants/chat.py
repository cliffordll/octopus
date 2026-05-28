from __future__ import annotations

from typing import Literal

ChatConversationStatus = Literal["active", "resolved", "archived"]
ChatIssueCreationMode = Literal["manual_approval", "auto_create"]
ChatMessageRole = Literal["user", "assistant", "system"]
ChatMessageKind = Literal[
    "message", "ask_user", "issue_proposal", "operation_proposal", "system_event"
]
ChatMessageStatus = Literal[
    "streaming", "completed", "stopped", "failed", "interrupted"
]
ChatContextEntityType = Literal["issue", "project", "agent"]

CHAT_CONVERSATION_STATUSES: tuple[ChatConversationStatus, ...] = (
    "active",
    "resolved",
    "archived",
)
CHAT_ISSUE_CREATION_MODES: tuple[ChatIssueCreationMode, ...] = (
    "manual_approval",
    "auto_create",
)
CHAT_MESSAGE_ROLES: tuple[ChatMessageRole, ...] = ("user", "assistant", "system")
CHAT_MESSAGE_KINDS: tuple[ChatMessageKind, ...] = (
    "message",
    "ask_user",
    "issue_proposal",
    "operation_proposal",
    "system_event",
)
CHAT_MESSAGE_STATUSES: tuple[ChatMessageStatus, ...] = (
    "streaming",
    "completed",
    "stopped",
    "failed",
    "interrupted",
)
CHAT_CONTEXT_ENTITY_TYPES: tuple[ChatContextEntityType, ...] = (
    "issue",
    "project",
    "agent",
)
