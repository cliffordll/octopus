from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from packages.shared.api_paths.activity import (
    HEARTBEAT_RUN_ISSUES_PATH,
    ISSUE_ACTIVITY_PATH,
    ISSUE_RUNS_PATH,
    ORG_ACTIVITY_PATH,
)
from packages.shared.types.activity import (
    ActivityEvent,
    ActivityQuery,
    IssueRunSummary,
    RunIssueSummary,
)
from packages.shared.validators.activity import (
    validate_activity_query,
    validate_create_activity,
)

from ..dependencies.access import (
    assert_organization_access,
    require_board_access,
    require_organization_access,
)
from ..dependencies.activity import get_activity_service
from ..dependencies.heartbeat import get_heartbeat_service
from ..services.activity import ActivityService
from ..services.heartbeat import HeartbeatService

router = APIRouter(tags=["activity"])


@router.get(ORG_ACTIVITY_PATH)
async def list_org_activity_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    service: ActivityService = Depends(get_activity_service),
    agentId: str | None = Query(default=None),
    userId: str | None = Query(default=None),
    actorType: str | None = Query(default=None),
    actorId: str | None = Query(default=None),
    action: str | None = Query(default=None),
    entityType: str | None = Query(default=None),
    entityId: str | None = Query(default=None),
    runId: str | None = Query(default=None),
    startTime: str | None = Query(default=None),
    endTime: str | None = Query(default=None),
    limit: int = Query(default=100),
    offset: int = Query(default=0),
) -> list[ActivityEvent]:
    query = _validated_query(
        {
            "agentId": agentId,
            "userId": userId,
            "actorType": actorType,
            "actorId": actorId,
            "action": action,
            "entityType": entityType,
            "entityId": entityId,
            "runId": runId,
            "startTime": startTime,
            "endTime": endTime,
            "limit": limit,
            "offset": offset,
        }
    )
    return await service.list_for_org(orgId, query)


@router.post(ORG_ACTIVITY_PATH, status_code=status.HTTP_201_CREATED)
async def create_org_activity_route(
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    service: ActivityService = Depends(get_activity_service),
) -> ActivityEvent:
    try:
        payload = validate_create_activity(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return await service.create(orgId, payload)


@router.get(ISSUE_ACTIVITY_PATH)
async def list_issue_activity_route(
    id: str,
    request: Request,
    service: ActivityService = Depends(get_activity_service),
) -> list[ActivityEvent]:
    issue = await service.resolve_issue(id)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found"
        )
    assert_organization_access(request, issue.org_id)
    events = await service.for_issue(issue.id)
    assert events is not None
    return events


@router.get(ISSUE_RUNS_PATH)
async def list_issue_runs_route(
    id: str,
    request: Request,
    service: ActivityService = Depends(get_activity_service),
) -> list[IssueRunSummary]:
    issue = await service.resolve_issue(id)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found"
        )
    assert_organization_access(request, issue.org_id)
    runs = await service.runs_for_issue(issue.id)
    assert runs is not None
    return runs


@router.get(HEARTBEAT_RUN_ISSUES_PATH)
async def list_heartbeat_run_issues_route(
    runId: str,
    request: Request,
    service: ActivityService = Depends(get_activity_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> list[RunIssueSummary]:
    run = await heartbeat.get(runId)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, run["orgId"])
    issues = await service.issues_for_run(runId)
    assert issues is not None
    return issues


def _validated_query(raw: dict[str, Any]) -> ActivityQuery:
    compact = {key: value for key, value in raw.items() if value is not None}
    try:
        return validate_activity_query(compact)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
