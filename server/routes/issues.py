from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.api_paths.issues import ISSUE_DETAIL_PATH, ORG_ISSUE_LIST_PATH
from packages.shared.types.issue import IssueDetail, IssueListItem
from packages.shared.validators.issue import validate_list_org_issues_query

from ..dependencies.database import get_session
from ..dependencies.issues import get_issue_service
from ..dependencies.ownership import (
    assert_organization_owned,
    require_organization_ownership,
)
from ..services.issues import IssueService

router = APIRouter(tags=["issues"])


@router.get("/api/issues")
async def org_issues_error_entry() -> None:
    raise HTTPException(
        status_code=http_status.HTTP_400_BAD_REQUEST,
        detail="Missing orgId in path. Use /api/orgs/{orgId}/issues.",
    )


@router.get(ORG_ISSUE_LIST_PATH)
async def list_org_issues_route(
    orgId: str,
    _: None = Depends(require_organization_ownership),
    service: IssueService = Depends(get_issue_service),
    status: str | None = Query(default=None),
    assigneeAgentId: str | None = Query(default=None),
) -> list[IssueListItem]:
    raw_query: dict[str, str] = {}
    if status is not None:
        raw_query["status"] = status
    if assigneeAgentId is not None:
        raw_query["assigneeAgentId"] = assigneeAgentId
    try:
        validated = validate_list_org_issues_query(raw_query)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return await service.list_for_org(
        orgId,
        status=validated.get("status"),
        assignee_agent_id=validated.get("assigneeAgentId"),
    )


@router.get(ISSUE_DETAIL_PATH)
async def get_issue_route(
    id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: IssueService = Depends(get_issue_service),
) -> IssueDetail:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await assert_organization_owned(request, session, detail["orgId"])
    return detail
