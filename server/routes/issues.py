from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.api_paths.issues import (
    ISSUE_COMMENT_LIST_PATH,
    ISSUE_DETAIL_PATH,
    ISSUE_LIST_MISSING_ORG_PATH,
    ISSUE_REVIEW_DECISION_PATH,
    ORG_ISSUE_LIST_PATH,
)
from packages.shared.types.issue import IssueDetail, IssueListItem
from packages.shared.validators.issue import (
    validate_create_issue,
    validate_create_issue_comment,
    validate_list_org_issues_query,
    validate_record_issue_review_decision,
    validate_update_issue,
)

from ..dependencies.database import get_session
from ..dependencies.issues import get_issue_service
from ..dependencies.ownership import (
    assert_organization_owned,
    require_organization_ownership,
)
from ..services.issues import IssueService

router = APIRouter(tags=["issues"])


@router.get(ISSUE_LIST_MISSING_ORG_PATH)
async def list_org_issues_missing_org_route() -> None:
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
    projectId: str | None = Query(default=None),
    goalId: str | None = Query(default=None),
    originKind: str | None = Query(default=None),
    originId: str | None = Query(default=None),
) -> list[IssueListItem]:
    raw_query: dict[str, str] = {}
    if status is not None:
        raw_query["status"] = status
    if assigneeAgentId is not None:
        raw_query["assigneeAgentId"] = assigneeAgentId
    if projectId is not None:
        raw_query["projectId"] = projectId
    if goalId is not None:
        raw_query["goalId"] = goalId
    if originKind is not None:
        raw_query["originKind"] = originKind
    if originId is not None:
        raw_query["originId"] = originId
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
        project_id=validated.get("projectId"),
        goal_id=validated.get("goalId"),
        origin_kind=validated.get("originKind"),
        origin_id=validated.get("originId"),
    )


@router.post(ORG_ISSUE_LIST_PATH)
async def create_issue_route(
    orgId: str,
    _: None = Depends(require_organization_ownership),
    service: IssueService = Depends(get_issue_service),
    body: dict[str, Any] = Body(...),
) -> IssueDetail:
    try:
        payload = validate_create_issue(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return await service.create_issue(
        orgId,
        payload,
        actor_type="board",
        actor_id="board",
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


@router.patch(ISSUE_DETAIL_PATH)
async def update_issue_route(
    id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: IssueService = Depends(get_issue_service),
    body: dict[str, Any] = Body(...),
) -> IssueDetail:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await assert_organization_owned(request, session, detail["orgId"])
    try:
        payload = validate_update_issue(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    try:
        updated = await service.update_issue(
            id,
            payload,
            actor_type="board",
            actor_id="board",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    return updated


@router.get(ISSUE_COMMENT_LIST_PATH)
async def list_issue_comments_route(
    id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: IssueService = Depends(get_issue_service),
) -> list[dict[str, Any]]:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await assert_organization_owned(request, session, detail["orgId"])
    comments = await service.list_comments(id)
    return [
        {
            "id": comment.id,
            "issueId": comment.issue_id,
            "body": comment.body,
            "authorAgentId": comment.author_agent_id,
            "authorUserId": comment.author_user_id,
            "createdAt": comment.created_at.isoformat(),
            "updatedAt": comment.updated_at.isoformat(),
        }
        for comment in comments
    ]


@router.post(ISSUE_COMMENT_LIST_PATH)
async def create_issue_comment_route(
    id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: IssueService = Depends(get_issue_service),
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await assert_organization_owned(request, session, detail["orgId"])
    try:
        payload = validate_create_issue_comment(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    comment = await service.add_comment(
        id,
        payload,
        actor_type="board",
        actor_id="board",
    )
    return {
        "id": comment.id,
        "issueId": comment.issue_id,
        "body": comment.body,
        "authorAgentId": comment.author_agent_id,
        "authorUserId": comment.author_user_id,
        "createdAt": comment.created_at.isoformat(),
        "updatedAt": comment.updated_at.isoformat(),
    }


@router.post(ISSUE_REVIEW_DECISION_PATH)
async def record_issue_review_decision_route(
    id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: IssueService = Depends(get_issue_service),
    body: dict[str, Any] = Body(...),
) -> IssueDetail:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await assert_organization_owned(request, session, detail["orgId"])
    try:
        payload = validate_record_issue_review_decision(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    try:
        updated = await service.update_issue(
            id,
            {"reviewDecision": payload},
            actor_type="board",
            actor_id="board",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    return updated
