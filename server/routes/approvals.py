from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.api_paths.approvals import (
    APPROVAL_DETAIL_PATH,
    ORG_APPROVAL_LIST_PATH,
)
from packages.shared.types.approval import ApprovalDetail, ApprovalListItem
from packages.shared.validators.approval import validate_list_org_approvals_query

from ..dependencies.approvals import get_approval_service
from ..dependencies.database import get_session
from ..dependencies.ownership import (
    assert_organization_owned,
    require_organization_ownership,
)
from ..services.approvals import ApprovalService

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
