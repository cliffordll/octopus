from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from .approval import ApprovalDetail
from .chat import ChatConversation, ChatMessage
from ..constants.messenger import MessengerThreadKind

MessengerThreadActionMethod = Literal["GET", "POST", "DELETE"]


class MessengerThreadUserState(TypedDict):
    id: str
    orgId: str
    userId: str
    threadKey: str
    lastReadAt: str
    createdAt: str
    updatedAt: str


class MessengerThreadAction(TypedDict):
    label: str
    href: str | None
    method: MessengerThreadActionMethod | None


class MessengerThreadSummary(TypedDict):
    threadKey: str
    kind: MessengerThreadKind
    title: str
    subtitle: str | None
    preview: str | None
    latestActivityAt: str | None
    lastReadAt: str | None
    unreadCount: int
    needsAttention: bool
    isPinned: bool
    href: str


class MessengerEvent(TypedDict):
    id: str
    threadKey: str
    kind: MessengerThreadKind
    title: str
    subtitle: str | None
    body: str | None
    preview: str | None
    href: str | None
    latestActivityAt: str
    actions: list[MessengerThreadAction]
    metadata: dict[str, Any]


class MessengerThreadItem(MessengerEvent):
    pass


class MessengerIssueThreadItem(MessengerThreadItem):
    issueId: str
    issueIdentifier: str | None
    sourceCommentId: str | None
    sourceCommentAuthorLabel: str | None
    sourceCommentBody: str | None


class MessengerApprovalThreadItem(MessengerThreadItem):
    approval: ApprovalDetail


class MessengerThreadDetail(TypedDict):
    threadKey: str
    kind: MessengerThreadKind
    title: str
    subtitle: str | None
    preview: str | None
    latestActivityAt: str | None
    lastReadAt: str | None
    unreadCount: int
    needsAttention: bool
    isPinned: bool
    href: str
    description: str | None
    items: list[dict[str, Any]]


class MessengerThreadBundle(TypedDict):
    summary: MessengerThreadSummary
    detail: MessengerThreadDetail


class MessengerChatThreadDetail(TypedDict):
    conversation: ChatConversation
    messages: list[ChatMessage]


class MarkMessengerThreadReadPayload(TypedDict, total=False):
    lastReadAt: NotRequired[str]


class MarkMessengerThreadReadResponse(TypedDict):
    threadKey: str
    lastReadAt: str
