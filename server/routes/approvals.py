from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi import status as http_status

from packages.shared.api_paths.approvals import (
    APPROVAL_COMMENTS_PATH,
    APPROVAL_DETAIL_PATH,
    APPROVAL_APPROVE_PATH,
    APPROVAL_ISSUES_PATH,
    APPROVAL_REQUEST_REVISION_PATH,
    APPROVAL_RESUBMIT_PATH,
    APPROVAL_REJECT_PATH,
    ORG_APPROVAL_LIST_PATH,
)
from packages.shared.types.approval import (
    ApprovalComment,
    ApprovalDetail,
    ApprovalListItem,
)
from packages.shared.types.issue import IssueListItem
from packages.shared.validators.approval import (
    validate_add_approval_comment,
    validate_create_approval,
    validate_list_org_approvals_query,
    validate_request_approval_revision,
    validate_resolve_approval,
    validate_resubmit_approval,
)

from ..dependencies.approvals import get_approval_service
from ..dependencies.access import (
    assert_organization_access,
    require_actor_identity,
    require_board_access,
    require_organization_access,
)
from ..services.approvals import ApprovalService

router = APIRouter(tags=["approvals"])


@router.get(ORG_APPROVAL_LIST_PATH)
async def list_org_approvals_route(
    orgId: str,
    _: None = Depends(require_organization_access),
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
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    assert_organization_access(request, detail["orgId"])
    return detail


@router.post(ORG_APPROVAL_LIST_PATH)
async def create_approval_route(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    __: None = Depends(require_organization_access),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    try:
        payload = validate_create_approval(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    try:
        return await service.create_approval(
            orgId,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


async def _get_approval_detail(
    request: Request,
    service: ApprovalService,
    approval_id: str,
) -> ApprovalDetail:
    detail = await service.get_by_id(approval_id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    assert_organization_access(request, detail["orgId"])
    return detail


@router.post(APPROVAL_APPROVE_PATH)
async def approve_approval_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    await _get_approval_detail(request, service, id)
    try:
        payload = validate_resolve_approval(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    try:
        updated = await service.approve_approval(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
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
    _: None = Depends(require_board_access),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    await _get_approval_detail(request, service, id)
    try:
        payload = validate_resolve_approval(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    try:
        updated = await service.reject_approval(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
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
    _: None = Depends(require_board_access),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    await _get_approval_detail(request, service, id)
    try:
        payload = validate_request_approval_revision(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    try:
        updated = await service.request_revision(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
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
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalDetail:
    await _get_approval_detail(request, service, id)
    try:
        payload = validate_resubmit_approval(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    try:
        updated = await service.resubmit_approval(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
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


@router.get(APPROVAL_ISSUES_PATH)
async def list_approval_issues_route(
    id: str,
    request: Request,
    service: ApprovalService = Depends(get_approval_service),
) -> list[IssueListItem]:
    detail = await _get_approval_detail(request, service, id)
    issues = await service.list_issues_for_approval(detail["id"])
    if issues is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    return issues


@router.get(APPROVAL_COMMENTS_PATH)
async def list_approval_comments_route(
    id: str,
    request: Request,
    service: ApprovalService = Depends(get_approval_service),
) -> list[ApprovalComment]:
    detail = await _get_approval_detail(request, service, id)
    comments = await service.list_comments(detail["id"])
    if comments is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    return comments


@router.post(APPROVAL_COMMENTS_PATH, status_code=http_status.HTTP_201_CREATED)
async def add_approval_comment_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalComment:
    detail = await _get_approval_detail(request, service, id)
    try:
        payload = validate_add_approval_comment(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    comment = await service.add_comment(
        detail["id"],
        payload,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if comment is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    return comment
