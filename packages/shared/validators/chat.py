from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
import uuid

from ..constants.chat import (
    CHAT_CONTEXT_ENTITY_TYPES,
    CHAT_CONVERSATION_STATUSES,
    CHAT_ISSUE_CREATION_MODES,
)
from ..types.chat import (
    AddChatMessagePayload,
    ConvertChatToIssuePayload,
    CreateChatAttachmentPayload,
    CreateChatContextLinkPayload,
    CreateChatConversationPayload,
    ResolveChatOperationProposalPayload,
    SetChatProjectContextPayload,
    UpdateChatConversationPayload,
    UpdateChatConversationUserStatePayload,
)

_CREATE_FIELDS = {
    "title",
    "summary",
    "preferredAgentId",
    "issueCreationMode",
    "planMode",
    "contextLinks",
}

_UPDATE_FIELDS = _CREATE_FIELDS | {
    "status",
    "routedAgentId",
    "primaryIssueId",
    "resolvedAt",
}

_CONVERT_ISSUE_FIELDS = {
    "messageId",
    "proposal",
}

_ISSUE_PROPOSAL_FIELDS = {
    "title",
    "description",
    "priority",
    "projectId",
    "goalId",
    "parentId",
    "assigneeAgentId",
    "assigneeUserId",
    "reviewerAgentId",
    "reviewerUserId",
    "labelIds",
    "requiresLabelSelection",
}

_OPERATION_DECISION_ACTIONS = {"approve", "reject", "requestRevision"}

_CREATE_ATTACHMENT_FIELDS = {
    "messageId",
    "provider",
    "objectKey",
    "contentType",
    "byteSize",
    "sha256",
    "originalFilename",
}


def validate_create_chat_conversation(
    payload: Mapping[str, Any],
) -> CreateChatConversationPayload:
    _reject_unknown_fields(payload, _CREATE_FIELDS)
    result = dict(payload)
    _validate_conversation_common(result)
    if "contextLinks" in result:
        if not isinstance(result["contextLinks"], list):
            raise ValueError("'contextLinks' must be a list")
        result["contextLinks"] = [
            validate_create_chat_context_link(link) for link in result["contextLinks"]
        ]
    return cast(CreateChatConversationPayload, result)


def validate_create_chat_context_link(
    payload: Mapping[str, Any],
) -> CreateChatContextLinkPayload:
    _reject_unknown_fields(payload, {"entityType", "entityId", "metadata"})
    result = dict(payload)
    if result.get("entityType") not in CHAT_CONTEXT_ENTITY_TYPES:
        raise ValueError(
            f"'entityType' must be one of {list(CHAT_CONTEXT_ENTITY_TYPES)}"
        )
    entity_id = result.get("entityId")
    if not isinstance(entity_id, str) or not entity_id.strip():
        raise ValueError("'entityId' must be a non-empty string")
    result["entityId"] = entity_id.strip()
    if "metadata" in result and result["metadata"] is not None:
        if not isinstance(result["metadata"], dict):
            raise ValueError("'metadata' must be an object or null")
    return cast(CreateChatContextLinkPayload, result)


def validate_set_chat_project_context(
    payload: Mapping[str, Any],
) -> SetChatProjectContextPayload:
    _reject_unknown_fields(payload, {"projectId"})
    result = dict(payload)
    if "projectId" in result and result["projectId"] is not None:
        _validate_uuid(result["projectId"], "projectId")
    return cast(SetChatProjectContextPayload, result)


def validate_convert_chat_to_issue(
    payload: Mapping[str, Any],
) -> ConvertChatToIssuePayload:
    _reject_unknown_fields(payload, _CONVERT_ISSUE_FIELDS)
    result = dict(payload)
    if "messageId" in result and result["messageId"] is not None:
        _validate_uuid(result["messageId"], "messageId")
    if "proposal" in result and result["proposal"] is not None:
        if not isinstance(result["proposal"], Mapping):
            raise ValueError("'proposal' must be an object or null")
        proposal = dict(result["proposal"])
        _reject_unknown_fields(proposal, _ISSUE_PROPOSAL_FIELDS)
        proposal["title"] = _trimmed_text(proposal.get("title"), "title", maximum=200)
        proposal["description"] = _trimmed_text(
            proposal.get("description"), "description", maximum=20000
        )
        if "priority" in proposal and proposal["priority"] not in {
            "critical",
            "high",
            "medium",
            "low",
        }:
            raise ValueError(
                "'priority' must be one of ['critical', 'high', 'medium', 'low']"
            )
        for field in (
            "projectId",
            "goalId",
            "parentId",
            "assigneeAgentId",
            "reviewerAgentId",
        ):
            if field in proposal and proposal[field] is not None:
                _validate_uuid(proposal[field], field)
        for field in ("assigneeUserId", "reviewerUserId"):
            if field in proposal and proposal[field] is not None:
                proposal[field] = _trimmed_text(
                    proposal[field], field, maximum=200, allow_empty=False
                )
        if "labelIds" in proposal:
            label_ids = proposal["labelIds"]
            if not isinstance(label_ids, list):
                raise ValueError("'labelIds' must be an array")
            for value in label_ids:
                _validate_uuid(value, "labelIds")
        if "requiresLabelSelection" in proposal and not isinstance(
            proposal["requiresLabelSelection"], bool
        ):
            raise ValueError("'requiresLabelSelection' must be a boolean")
        result["proposal"] = proposal
    return cast(ConvertChatToIssuePayload, result)


def validate_resolve_chat_operation_proposal(
    payload: Mapping[str, Any],
) -> ResolveChatOperationProposalPayload:
    _reject_unknown_fields(payload, {"action", "decisionNote"})
    result = dict(payload)
    if result.get("action") not in _OPERATION_DECISION_ACTIONS:
        raise ValueError(
            f"'action' must be one of {sorted(_OPERATION_DECISION_ACTIONS)}"
        )
    if "decisionNote" in result and result["decisionNote"] is not None:
        result["decisionNote"] = _trimmed_text(
            result["decisionNote"],
            "decisionNote",
            maximum=5000,
            allow_empty=True,
        )
    return cast(ResolveChatOperationProposalPayload, result)


def validate_update_chat_conversation(
    payload: Mapping[str, Any],
) -> UpdateChatConversationPayload:
    _reject_unknown_fields(payload, _UPDATE_FIELDS)
    result = dict(payload)
    _validate_conversation_common(result)
    if "status" in result and result["status"] not in CHAT_CONVERSATION_STATUSES:
        raise ValueError(f"'status' must be one of {list(CHAT_CONVERSATION_STATUSES)}")
    for field in ("routedAgentId", "primaryIssueId"):
        if field in result and result[field] is not None:
            _validate_uuid(result[field], field)
    if "resolvedAt" in result and result["resolvedAt"] is not None:
        if not isinstance(result["resolvedAt"], str):
            raise ValueError("'resolvedAt' must be an ISO datetime string or null")
    return cast(UpdateChatConversationPayload, result)


def validate_update_chat_conversation_user_state(
    payload: Mapping[str, Any],
) -> UpdateChatConversationUserStatePayload:
    _reject_unknown_fields(payload, {"pinned", "unread"})
    result = dict(payload)
    for field in ("pinned", "unread"):
        if field in result and not isinstance(result[field], bool):
            raise ValueError(f"'{field}' must be a boolean")
    return cast(UpdateChatConversationUserStatePayload, result)


def _validate_conversation_common(result: dict[str, Any]) -> None:
    if "title" in result:
        result["title"] = _trimmed_text(result["title"], "title", maximum=200)
    if "summary" in result and result["summary"] is not None:
        result["summary"] = _trimmed_text(
            result["summary"], "summary", maximum=5000, allow_empty=True
        )
    if "preferredAgentId" in result and result["preferredAgentId"] is not None:
        _validate_uuid(result["preferredAgentId"], "preferredAgentId")
    if (
        "issueCreationMode" in result
        and result["issueCreationMode"] not in CHAT_ISSUE_CREATION_MODES
    ):
        raise ValueError(
            f"'issueCreationMode' must be one of {list(CHAT_ISSUE_CREATION_MODES)}"
        )
    if "planMode" in result and not isinstance(result["planMode"], bool):
        raise ValueError("'planMode' must be a boolean")


def validate_add_chat_message(payload: Mapping[str, Any]) -> AddChatMessagePayload:
    _reject_unknown_fields(payload, {"body", "editUserMessageId"})
    if "body" not in payload:
        raise ValueError("'body' is required")
    result: dict[str, Any] = {
        "body": _trimmed_text(payload["body"], "body", maximum=20000)
    }
    if "editUserMessageId" in payload:
        edit_user_message_id = payload["editUserMessageId"]
        if edit_user_message_id is not None:
            _validate_uuid(edit_user_message_id, "editUserMessageId")
        result["editUserMessageId"] = edit_user_message_id
    return cast(AddChatMessagePayload, result)


def validate_create_chat_attachment_metadata(
    payload: Mapping[str, Any],
) -> CreateChatAttachmentPayload:
    _reject_unknown_fields(payload, _CREATE_ATTACHMENT_FIELDS)
    result = dict(payload)
    for field in ("messageId", "provider", "objectKey", "contentType", "sha256"):
        if field not in result:
            raise ValueError(f"'{field}' is required")
    _validate_uuid(result["messageId"], "messageId")
    result["provider"] = _trimmed_text(result["provider"], "provider", maximum=100)
    result["objectKey"] = _trimmed_text(result["objectKey"], "objectKey", maximum=2000)
    result["contentType"] = _trimmed_text(
        result["contentType"], "contentType", maximum=200
    )
    result["sha256"] = _trimmed_text(result["sha256"], "sha256", maximum=200)
    byte_size = result.get("byteSize")
    if not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size <= 0:
        raise ValueError("'byteSize' must be a positive integer")
    if "originalFilename" in result and result["originalFilename"] is not None:
        result["originalFilename"] = _trimmed_text(
            result["originalFilename"],
            "originalFilename",
            maximum=500,
            allow_empty=True,
        )
    return cast(CreateChatAttachmentPayload, result)


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: set[str]) -> None:
    for field in payload:
        if field not in allowed:
            raise ValueError(f"Unsupported field: '{field}'")


def _validate_uuid(value: Any, field: str) -> None:
    try:
        uuid.UUID(str(value))
    except ValueError as exc:
        raise ValueError(f"'{field}' must be a UUID or null") from exc


def _trimmed_text(
    value: Any, field: str, *, maximum: int, allow_empty: bool = False
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"'{field}' must be a string")
    result = value.strip()
    if not result and not allow_empty:
        raise ValueError(f"'{field}' must be a non-empty string")
    if len(result) > maximum:
        raise ValueError(f"'{field}' must contain at most {maximum} characters")
    return result
