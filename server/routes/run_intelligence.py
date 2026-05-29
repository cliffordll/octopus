from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from packages.shared.api_paths.run_intelligence import (
    RUN_INTELLIGENCE_ORG_RUNS_PATH,
    RUN_INTELLIGENCE_RUN_EVENTS_PATH,
    RUN_INTELLIGENCE_RUN_LOG_PATH,
    RUN_INTELLIGENCE_RUN_PATH,
)
from packages.shared.types.heartbeat import HeartbeatRunEvent

from ..dependencies.access import assert_organization_access
from ..dependencies.run_intelligence import get_run_intelligence_service
from ..services.run_intelligence import RunIntelligenceService

router = APIRouter(tags=["run-intelligence"])


@router.get(RUN_INTELLIGENCE_ORG_RUNS_PATH)
async def list_run_intelligence_runs_route(
    orgId: str,
    request: Request,
    updatedAfter: str | None = None,
    createdBefore: str | None = None,
    runIdPrefix: str | None = None,
    agentId: str | None = None,
    status: str | None = None,
    runtime: str | None = None,
    issueId: str | None = None,
    limit: int = 200,
    service: RunIntelligenceService = Depends(get_run_intelligence_service),
) -> list[dict[str, Any]]:
    assert_organization_access(request, orgId)
    return await service.list_runs(
        orgId,
        updated_after=updatedAfter,
        created_before=createdBefore,
        run_id_prefix=runIdPrefix,
        agent_id=agentId,
        status=status,
        runtime=runtime,
        issue_id=issueId,
        limit=limit,
    )


@router.get(RUN_INTELLIGENCE_RUN_PATH)
async def get_run_intelligence_run_route(
    runId: str,
    request: Request,
    service: RunIntelligenceService = Depends(get_run_intelligence_service),
) -> dict[str, Any]:
    observed = await service.get_run(runId)
    if observed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, observed["run"]["orgId"])
    return observed


@router.get(RUN_INTELLIGENCE_RUN_EVENTS_PATH)
async def list_run_intelligence_run_events_route(
    runId: str,
    request: Request,
    service: RunIntelligenceService = Depends(get_run_intelligence_service),
) -> list[HeartbeatRunEvent]:
    observed = await service.get_run(runId)
    if observed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, observed["run"]["orgId"])
    events = await service.list_events(runId)
    assert events is not None
    return events


@router.get(RUN_INTELLIGENCE_RUN_LOG_PATH)
async def get_run_intelligence_run_log_route(
    runId: str,
    request: Request,
    service: RunIntelligenceService = Depends(get_run_intelligence_service),
) -> dict[str, str]:
    observed = await service.get_run(runId)
    if observed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat run not found"
        )
    assert_organization_access(request, observed["run"]["orgId"])
    log = await service.read_log(runId)
    assert log is not None
    return log
