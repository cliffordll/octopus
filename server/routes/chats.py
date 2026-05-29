from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from packages.shared.api_paths.chats import (
    CHAT_CONVERT_TO_ISSUE_PATH,
    CHAT_CONTEXT_LINKS_PATH,
    CHAT_DETAIL_PATH,
    CHAT_MESSAGES_PATH,
    CHAT_MESSAGES_STREAM_PATH,
    CHAT_MESSAGES_STREAM_STOP_PATH,
    CHAT_OPERATION_PROPOSAL_RESOLVE_PATH,
    CHAT_PROJECT_CONTEXT_PATH,
    CHAT_USER_STATE_PATH,
    ORG_CHAT_LIST_PATH,
)
from packages.shared.types.chat import (
    ChatContextLink,
    ChatConversation,
    ChatMessage,
)
from packages.shared.validators.chat import (
    validate_add_chat_message,
    validate_convert_chat_to_issue,
    validate_create_chat_context_link,
    validate_create_chat_conversation,
    validate_resolve_chat_operation_proposal,
    validate_set_chat_project_context,
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
_ACTIVE_STREAM_CANCEL_EVENTS: dict[str, asyncio.Event] = {}


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


@router.post(CHAT_CONTEXT_LINKS_PATH, status_code=status.HTTP_201_CREATED)
async def add_chat_context_link_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ChatService = Depends(get_chat_service),
) -> ChatContextLink:
    current = await _get_conversation_or_404(id, request=request, service=service)
    try:
        payload = validate_create_chat_context_link(body)
        actor = require_actor_identity(request)
        linked = await service.add_context_link(
            current["id"],
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if linked is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat conversation not found",
        )
    return linked


@router.post(CHAT_PROJECT_CONTEXT_PATH)
async def set_chat_project_context_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ChatService = Depends(get_chat_service),
) -> ChatConversation:
    current = await _get_conversation_or_404(id, request=request, service=service)
    try:
        payload = validate_set_chat_project_context(body)
        actor = require_actor_identity(request)
        updated = await service.set_project_context(
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


@router.get(CHAT_MESSAGES_PATH)
async def list_chat_messages_route(
    id: str,
    request: Request,
    service: ChatService = Depends(get_chat_service),
) -> list[ChatMessage]:
    await _get_conversation_or_404(id, request=request, service=service)
    return await service.list_messages(id)


@router.post(CHAT_CONVERT_TO_ISSUE_PATH, status_code=status.HTTP_201_CREATED)
async def convert_chat_to_issue_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ChatService = Depends(get_chat_service),
) -> dict[str, Any]:
    await _get_conversation_or_404(id, request=request, service=service)
    try:
        payload = validate_convert_chat_to_issue(body)
        actor = require_actor_identity(request)
        result = await service.convert_to_issue(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat conversation not found",
        )
    return result


@router.post(CHAT_OPERATION_PROPOSAL_RESOLVE_PATH, status_code=status.HTTP_201_CREATED)
async def resolve_chat_operation_proposal_route(
    id: str,
    messageId: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ChatService = Depends(get_chat_service),
) -> dict[str, Any]:
    await _get_conversation_or_404(id, request=request, service=service)
    try:
        payload = validate_resolve_chat_operation_proposal(body)
        actor = require_actor_identity(request)
        result = await service.resolve_operation_proposal(
            id,
            messageId,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat conversation not found",
        )
    return result


@router.post(CHAT_MESSAGES_PATH, status_code=status.HTTP_201_CREATED)
async def add_chat_message_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ChatService = Depends(get_chat_service),
) -> Any:
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
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": str(exc)},
        )


@router.post(CHAT_MESSAGES_STREAM_PATH, status_code=status.HTTP_201_CREATED)
async def add_chat_message_stream_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    await _get_conversation_or_404(id, request=request, service=service)
    try:
        payload = validate_add_chat_message(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    if id in _ACTIVE_STREAM_CANCEL_EVENTS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A chat reply is already being generated for this conversation",
        )

    cancel_event = asyncio.Event()
    _ACTIVE_STREAM_CANCEL_EVENTS[id] = cancel_event

    async def event_stream():
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def on_stream_event(event: dict[str, Any]) -> None:
            await queue.put(event)

        task = asyncio.create_task(
            service.add_message_and_reply(
                id,
                payload,
                cancel_event=cancel_event,
                on_stream_event=on_stream_event,
            )
        )
        try:
            while True:
                if task.done() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                except TimeoutError:
                    continue
                if event is None:
                    continue
                yield _stream_line(event)
            result = await task
            yield _stream_line({"type": "final", "messages": result["messages"]})
        except Exception as exc:
            if not task.done():
                task.cancel()
            yield _stream_line({"type": "error", "error": str(exc), "messageId": None})
        finally:
            _ACTIVE_STREAM_CANCEL_EVENTS.pop(id, None)

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        status_code=status.HTTP_201_CREATED,
    )


@router.post(CHAT_MESSAGES_STREAM_STOP_PATH)
async def stop_chat_message_stream_route(
    id: str,
    request: Request,
    service: ChatService = Depends(get_chat_service),
) -> dict[str, bool]:
    await _get_conversation_or_404(id, request=request, service=service)
    cancel_event = _ACTIVE_STREAM_CANCEL_EVENTS.get(id)
    if cancel_event is None:
        return {"stopped": False}
    cancel_event.set()
    return {"stopped": True}


def _stream_line(event: dict[str, Any]) -> str:
    return json.dumps(event, separators=(",", ":")) + "\n"
