from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from ..constants.chat import (
    ChatConversationStatus,
    ChatIssueCreationMode,
    ChatMessageKind,
    ChatMessageRole,
    ChatMessageStatus,
)


class ChatConversation(TypedDict):
    id: str
    orgId: str
    status: ChatConversationStatus
    title: str
    summary: str | None
    preferredAgentId: str | None
    routedAgentId: str | None
    primaryIssueId: str | None
    issueCreationMode: ChatIssueCreationMode
    planMode: bool
    createdByUserId: str | None
    lastMessageAt: str | None
    resolvedAt: str | None
    createdAt: str
    updatedAt: str


class ChatMessage(TypedDict):
    id: str
    orgId: str
    conversationId: str
    role: ChatMessageRole
    kind: ChatMessageKind
    status: ChatMessageStatus
    body: str
    structuredPayload: dict[str, Any] | None
    approvalId: str | None
    replyingAgentId: str | None
    chatTurnId: str | None
    turnVariant: int
    supersededAt: str | None
    createdAt: str
    updatedAt: str


class CreateChatConversationPayload(TypedDict, total=False):
    title: NotRequired[str]
    summary: NotRequired[str | None]
    preferredAgentId: NotRequired[str | None]
    issueCreationMode: NotRequired[ChatIssueCreationMode]
    planMode: NotRequired[bool]


class AddChatMessagePayload(TypedDict):
    body: str


class CreatedChatMessages(TypedDict):
    messages: list[ChatMessage]
