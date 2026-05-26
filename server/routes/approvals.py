from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.api_paths.approvals import (
    APPROVAL_DETAIL_PATH,
    APPROVAL_APPROVE_PATH,
    APPROVAL_REQUEST_REVISION_PATH,
    APPROVAL_RESUBMIT_PATH,
    APPROVAL_REJECT_PATH,
    ORG_APPROVAL_LIST_PATH,
)
from packages.shared.types.approval import ApprovalDetail, ApprovalListItem
from packages.shared.validators.approval import (
    validate_create_approval,
    validate_list_org_approvals_query,
    validate_request_approval_revision,
    validate_resolve_approval,
    validate_resubmit_approval,
)

from ..dependencies.approvals import get_approval_service
from ..dependencies.database import get_session
from ..dependencies.ownership import (
    assert_organization_owned,
    require_organization_ownership,
)
from ..services.approvals import ApprovalService
from .orgs import _extract_actor_identity, require_board_access

router = APIRouter(tags=["approvals"])


@router.get(ORG_APPROVAL_LIST_PATH)
async def list_org_approvals_route(
    orgId: str,
    _: None = Depends(require_organization_ownership),
    service: ApprovalService = Depends(get_approval_service),
    status: str | None = Query(default=None),
) -> list[ApprovalListItem]:
    raw_query: dict[str, str] = {}
    if status is not None:
        raw_query["status"] = status
    try:
        validated = validate_list_org_approvals_query(raw_query)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return await service.list_for_org(orgId, status=validated.get("status"))


@router.get(APPROVAL_DETAIL_PATH)
async def get_approval_route(
    id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    await assert_organization_owned(request, session, detail["orgId"])
    return detail


@router.post(ORG_APPROVAL_LIST_PATH)
async def create_approval_route(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_ownership),
    __: None = Depends(require_board_access),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    try:
        payload = validate_create_approval(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor_type, actor_id = _extract_actor_identity(request)
    return await service.create_approval(
        orgId,
        payload,
        actor_type=actor_type,
        actor_id=actor_id,
    )


async def _get_owned_approval_detail(
    request: Request,
    session: AsyncSession,
    service: ApprovalService,
    approval_id: str,
) -> ApprovalDetail:
    detail = await service.get_by_id(approval_id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    await assert_organization_owned(request, session, detail["orgId"])
    return detail


@router.post(APPROVAL_APPROVE_PATH)
async def approve_approval_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_board_access),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    await _get_owned_approval_detail(request, session, service, id)
    try:
        payload = validate_resolve_approval(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor_type, actor_id = _extract_actor_identity(request)
    updated = await service.approve_approval(
        id,
        payload,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    return updated


@router.post(APPROVAL_REJECT_PATH)
async def reject_approval_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_board_access),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    await _get_owned_approval_detail(request, session, service, id)
    try:
        payload = validate_resolve_approval(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor_type, actor_id = _extract_actor_identity(request)
    updated = await service.reject_approval(
        id,
        payload,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    return updated


@router.post(APPROVAL_REQUEST_REVISION_PATH)
async def request_approval_revision_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_board_access),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    await _get_owned_approval_detail(request, session, service, id)
    try:
        payload = validate_request_approval_revision(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor_type, actor_id = _extract_actor_identity(request)
    updated = await service.request_revision(
        id,
        payload,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    return updated


@router.post(APPROVAL_RESUBMIT_PATH)
async def resubmit_approval_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    await _get_owned_approval_detail(request, session, service, id)
    try:
        payload = validate_resubmit_approval(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor_type, actor_id = _extract_actor_identity(request)
    try:
        updated = await service.resubmit_approval(
            id,
            payload,
            actor_type=actor_type,
            actor_id=actor_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    return updated
