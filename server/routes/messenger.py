from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from packages.shared.api_paths.messenger import (
    ORG_MESSENGER_APPROVALS_PATH,
    ORG_MESSENGER_CHAT_THREAD_PATH,
    ORG_MESSENGER_ISSUES_PATH,
    ORG_MESSENGER_SYSTEM_THREAD_PATH,
    ORG_MESSENGER_THREAD_READ_PATH,
    ORG_MESSENGER_THREADS_PATH,
)
from packages.shared.constants.messenger import (
    MESSENGER_SYSTEM_THREAD_KINDS,
    MessengerSystemThreadKind,
)
from packages.shared.types.messenger import (
    MarkMessengerThreadReadResponse,
    MessengerChatThreadDetail,
    MessengerThreadBundle,
    MessengerThreadSummary,
)

from ..dependencies.access import require_actor_identity, require_organization_access
from ..dependencies.messenger import get_messenger_service
from ..services.messenger import MessengerService

router = APIRouter(tags=["messenger"])


@router.get(ORG_MESSENGER_THREADS_PATH)
async def list_messenger_threads_route(
    request: Request,
    orgId: str,
    _: None = Depends(require_organization_access),
    service: MessengerService = Depends(get_messenger_service),
) -> list[MessengerThreadSummary]:
    actor = require_actor_identity(request)
    return await service.list_thread_summaries(orgId, actor.actor_id)


@router.get(ORG_MESSENGER_CHAT_THREAD_PATH)
async def get_messenger_chat_thread_route(
    request: Request,
    orgId: str,
    conversationId: str,
    _: None = Depends(require_organization_access),
    service: MessengerService = Depends(get_messenger_service),
) -> MessengerChatThreadDetail:
    actor = require_actor_identity(request)
    thread = await service.get_chat_thread(orgId, conversationId, actor.actor_id)
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat conversation not found",
        )
    return thread


@router.post(ORG_MESSENGER_THREAD_READ_PATH)
async def mark_messenger_thread_read_route(
    request: Request,
    orgId: str,
    threadKey: str,
    body: dict[str, Any] = Body(default_factory=dict),
    _: None = Depends(require_organization_access),
    service: MessengerService = Depends(get_messenger_service),
) -> MarkMessengerThreadReadResponse:
    actor = require_actor_identity(request)
    last_read_at = _parse_optional_datetime(body.get("lastReadAt"))
    state = await service.mark_thread_read(
        orgId, actor.actor_id, threadKey, last_read_at=last_read_at
    )
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Messenger thread not found",
        )
    return state


@router.get(ORG_MESSENGER_ISSUES_PATH)
async def get_messenger_issues_route(
    request: Request,
    orgId: str,
    _: None = Depends(require_organization_access),
    service: MessengerService = Depends(get_messenger_service),
) -> MessengerThreadBundle:
    actor = require_actor_identity(request)
    return await service.get_issues_thread(orgId, actor.actor_id)


@router.get(ORG_MESSENGER_APPROVALS_PATH)
async def get_messenger_approvals_route(
    request: Request,
    orgId: str,
    _: None = Depends(require_organization_access),
    service: MessengerService = Depends(get_messenger_service),
) -> MessengerThreadBundle:
    actor = require_actor_identity(request)
    return await service.get_approvals_thread(orgId, actor.actor_id)


@router.get(ORG_MESSENGER_SYSTEM_THREAD_PATH)
async def get_messenger_system_thread_route(
    request: Request,
    orgId: str,
    threadKind: str,
    _: None = Depends(require_organization_access),
    service: MessengerService = Depends(get_messenger_service),
) -> MessengerThreadBundle:
    if threadKind not in MESSENGER_SYSTEM_THREAD_KINDS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Messenger system thread not found",
        )
    actor = require_actor_identity(request)
    thread = await service.get_system_thread(
        orgId, actor.actor_id, cast(MessengerSystemThreadKind, threadKind)
    )
    if thread is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Messenger system thread not found",
        )
    return thread


def _parse_optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="lastReadAt must be an ISO datetime",
        ) from exc
