from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from ..constants.chat import (
    ChatContextEntityType,
    ChatConversationStatus,
    ChatIssueCreationMode,
    ChatMessageKind,
    ChatMessageRole,
    ChatMessageStatus,
)


class ChatLinkedEntity(TypedDict, total=False):
    type: ChatContextEntityType
    id: str
    label: str
    subtitle: str | None
    identifier: str | None
    status: str | None
    parentId: str | None
    href: str


class ChatContextLink(TypedDict):
    id: str
    orgId: str
    conversationId: str
    entityType: ChatContextEntityType
    entityId: str
    metadata: dict[str, Any] | None
    entity: ChatLinkedEntity | None
    createdAt: str
    updatedAt: str


class ChatPrimaryIssueSummary(TypedDict):
    id: str
    identifier: str | None
    title: str
    status: str
    priority: str


class ChatRuntimeDescriptor(TypedDict):
    sourceType: str
    sourceLabel: str
    runtimeAgentId: str | None
    agentRuntimeType: str | None
    model: str | None
    available: bool
    error: str | None


class ChatAttachment(TypedDict):
    id: str
    orgId: str
    conversationId: str
    messageId: str
    assetId: str
    provider: str
    objectKey: str
    contentType: str
    byteSize: int
    sha256: str
    originalFilename: str | None
    createdByAgentId: str | None
    createdByUserId: str | None
    createdAt: str
    updatedAt: str
    contentPath: str


class ChatStreamTranscriptTodoItem(TypedDict):
    text: str
    status: str


class ChatStreamTranscriptEntry(TypedDict, total=False):
    kind: str
    ts: str
    text: str
    delta: NotRequired[bool]
    name: NotRequired[str]
    input: NotRequired[Any]
    toolUseId: NotRequired[str]
    toolName: NotRequired[str]
    content: NotRequired[str]
    isError: NotRequired[bool]
    todoListId: NotRequired[str]
    items: NotRequired[list[ChatStreamTranscriptTodoItem]]
    model: NotRequired[str]
    sessionId: NotRequired[str]
    inputTokens: NotRequired[int]
    outputTokens: NotRequired[int]
    cachedTokens: NotRequired[int]
    costUsd: NotRequired[float]
    subtype: NotRequired[str]
    errors: NotRequired[list[str]]


class ChatConversation(TypedDict):
    id: str
    orgId: str
    status: ChatConversationStatus
    title: str
    summary: str | None
    latestReplyPreview: str | None
    searchPreview: NotRequired[str | None]
    preferredAgentId: str | None
    routedAgentId: str | None
    primaryIssueId: str | None
    primaryIssue: ChatPrimaryIssueSummary | None
    issueCreationMode: ChatIssueCreationMode
    planMode: bool
    createdByUserId: str | None
    lastMessageAt: str | None
    lastReadAt: str | None
    isPinned: bool
    isUnread: bool
    unreadCount: int
    needsAttention: bool
    resolvedAt: str | None
    contextLinks: list[ChatContextLink]
    chatRuntime: ChatRuntimeDescriptor
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
    attachments: list[ChatAttachment]
    transcript: list[ChatStreamTranscriptEntry]
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
    contextLinks: NotRequired[list[CreateChatContextLinkPayload]]


class CreateChatContextLinkPayload(TypedDict):
    entityType: ChatContextEntityType
    entityId: str
    metadata: NotRequired[dict[str, Any] | None]


class UpdateChatConversationPayload(TypedDict, total=False):
    title: NotRequired[str]
    summary: NotRequired[str | None]
    preferredAgentId: NotRequired[str | None]
    issueCreationMode: NotRequired[ChatIssueCreationMode]
    planMode: NotRequired[bool]
    status: NotRequired[ChatConversationStatus]
    routedAgentId: NotRequired[str | None]
    primaryIssueId: NotRequired[str | None]
    resolvedAt: NotRequired[str | None]


class UpdateChatConversationUserStatePayload(TypedDict, total=False):
    pinned: NotRequired[bool]
    unread: NotRequired[bool]


class SetChatProjectContextPayload(TypedDict, total=False):
    projectId: NotRequired[str | None]


class ConvertChatToIssuePayload(TypedDict, total=False):
    messageId: NotRequired[str | None]
    proposal: NotRequired[dict[str, Any] | None]


class ResolveChatOperationProposalPayloadBase(TypedDict):
    action: str


class ResolveChatOperationProposalPayload(
    ResolveChatOperationProposalPayloadBase, total=False
):
    decisionNote: NotRequired[str | None]


class AddChatMessagePayloadBase(TypedDict):
    body: str


class AddChatMessagePayload(AddChatMessagePayloadBase, total=False):
    editUserMessageId: NotRequired[str | None]


class CreateChatAttachmentPayload(TypedDict):
    messageId: str
    provider: str
    objectKey: str
    contentType: str
    byteSize: int
    sha256: str
    originalFilename: NotRequired[str | None]


class CreatedChatMessages(TypedDict):
    messages: list[ChatMessage]


class ChatStreamEvent(TypedDict, total=False):
    type: Literal[
        "ack",
        "assistant_delta",
        "assistant_state",
        "transcript_entry",
        "final",
        "error",
    ]
    userMessage: NotRequired[ChatMessage]
    delta: NotRequired[str]
    state: NotRequired[dict[str, Any]]
    entry: NotRequired[ChatStreamTranscriptEntry]
    messages: NotRequired[list[ChatMessage]]
    error: NotRequired[str]
    messageId: NotRequired[str | None]
