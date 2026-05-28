from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from packages.shared.api_paths.chats import (
    CHAT_DETAIL_PATH,
    CHAT_MESSAGES_PATH,
    CHAT_USER_STATE_PATH,
    ORG_CHAT_LIST_PATH,
)
from packages.shared.types.chat import (
    ChatConversation,
    ChatMessage,
    CreatedChatMessages,
)
from packages.shared.validators.chat import (
    validate_add_chat_message,
    validate_create_chat_conversation,
    validate_update_chat_conversation,
    validate_update_chat_conversation_user_state,
)

from ..dependencies.access import (
    assert_organization_access,
    require_actor_identity,
    require_organization_access,
)
from ..dependencies.chats import get_chat_service
from ..services.chats import ChatAvailabilityError, ChatService

router = APIRouter(tags=["chats"])


async def _get_conversation_or_404(
    conversation_id: str,
    *,
    request: Request,
    service: ChatService,
    user_id: str | None = None,
) -> ChatConversation:
    conversation = await service.get(conversation_id, user_id=user_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat conversation not found",
        )
    assert_organization_access(request, conversation["orgId"])
    return conversation


@router.get(ORG_CHAT_LIST_PATH)
async def list_chats_route(
    request: Request,
    orgId: str,
    status: str = "active",
    q: str | None = None,
    _: None = Depends(require_organization_access),
    service: ChatService = Depends(get_chat_service),
) -> list[ChatConversation]:
    actor = require_actor_identity(request)
    return await service.list_for_org(orgId, status=status, q=q, user_id=actor.actor_id)


@router.post(ORG_CHAT_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_chat_route(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: ChatService = Depends(get_chat_service),
) -> ChatConversation:
    try:
        payload = validate_create_chat_conversation(body)
        actor = require_actor_identity(request)
        return await service.create(
            orgId, payload, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get(CHAT_DETAIL_PATH)
async def get_chat_route(
    id: str,
    request: Request,
    service: ChatService = Depends(get_chat_service),
) -> ChatConversation:
    actor = require_actor_identity(request)
    return await _get_conversation_or_404(
        id, request=request, service=service, user_id=actor.actor_id
    )


@router.patch(CHAT_DETAIL_PATH)
async def update_chat_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ChatService = Depends(get_chat_service),
) -> ChatConversation:
    current = await _get_conversation_or_404(id, request=request, service=service)
    try:
        payload = validate_update_chat_conversation(body)
        actor = require_actor_identity(request)
        updated = await service.update(
            current["id"],
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat conversation not found",
        )
    return updated


@router.patch(CHAT_USER_STATE_PATH)
async def update_chat_user_state_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ChatService = Depends(get_chat_service),
) -> ChatConversation:
    current = await _get_conversation_or_404(id, request=request, service=service)
    try:
        payload = validate_update_chat_conversation_user_state(body)
        actor = require_actor_identity(request)
        updated = await service.update_user_state(
            current["id"], payload, user_id=actor.actor_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat conversation not found",
        )
    return updated


@router.get(CHAT_MESSAGES_PATH)
async def list_chat_messages_route(
    id: str,
    request: Request,
    service: ChatService = Depends(get_chat_service),
) -> list[ChatMessage]:
    await _get_conversation_or_404(id, request=request, service=service)
    return await service.list_messages(id)


@router.post(CHAT_MESSAGES_PATH, status_code=status.HTTP_201_CREATED)
async def add_chat_message_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ChatService = Depends(get_chat_service),
) -> CreatedChatMessages:
    await _get_conversation_or_404(id, request=request, service=service)
    try:
        payload = validate_add_chat_message(body)
        return await service.add_message_and_reply(id, payload)
    except ChatAvailabilityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
