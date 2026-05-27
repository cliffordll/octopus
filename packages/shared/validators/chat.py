from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
import uuid

from ..constants.chat import CHAT_ISSUE_CREATION_MODES
from ..types.chat import AddChatMessagePayload, CreateChatConversationPayload

_CREATE_FIELDS = {
    "title",
    "summary",
    "preferredAgentId",
    "issueCreationMode",
    "planMode",
}


def validate_create_chat_conversation(
    payload: Mapping[str, Any],
) -> CreateChatConversationPayload:
    _reject_unknown_fields(payload, _CREATE_FIELDS)
    result = dict(payload)
    if "title" in result:
        result["title"] = _trimmed_text(result["title"], "title", maximum=200)
    if "summary" in result and result["summary"] is not None:
        result["summary"] = _trimmed_text(
            result["summary"], "summary", maximum=5000, allow_empty=True
        )
    if "preferredAgentId" in result and result["preferredAgentId"] is not None:
        try:
            uuid.UUID(str(result["preferredAgentId"]))
        except ValueError as exc:
            raise ValueError("'preferredAgentId' must be a UUID or null") from exc
    if (
        "issueCreationMode" in result
        and result["issueCreationMode"] not in CHAT_ISSUE_CREATION_MODES
    ):
        raise ValueError(
            f"'issueCreationMode' must be one of {list(CHAT_ISSUE_CREATION_MODES)}"
        )
    if "planMode" in result and not isinstance(result["planMode"], bool):
        raise ValueError("'planMode' must be a boolean")
    return cast(CreateChatConversationPayload, result)


def validate_add_chat_message(payload: Mapping[str, Any]) -> AddChatMessagePayload:
    _reject_unknown_fields(payload, {"body"})
    if "body" not in payload:
        raise ValueError("'body' is required")
    return {"body": _trimmed_text(payload["body"], "body", maximum=20000)}


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: set[str]) -> None:
    for field in payload:
        if field not in allowed:
            raise ValueError(f"Unsupported field: '{field}'")


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
