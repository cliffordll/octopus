from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from packages.shared.api_paths.costs import (
    ORG_COST_BY_AGENT_MODEL_PATH,
    ORG_COST_BY_AGENT_PATH,
    ORG_COST_BY_BILLER_PATH,
    ORG_COST_BY_PROJECT_PATH,
    ORG_COST_BY_PROVIDER_PATH,
    ORG_COST_EVENT_LIST_PATH,
    ORG_COST_SUMMARY_PATH,
    ORG_COST_TREND_PATH,
    ORG_COST_WINDOW_SPEND_PATH,
)
from packages.shared.types.cost import (
    CostDimensionRow,
    CostEvent,
    CostQuery,
    CostSummary,
    CostTrendRow,
    CostWindowSpend,
)
from packages.shared.validators.cost import (
    validate_cost_query,
    validate_create_cost_event,
)

from ..dependencies.access import require_actor_identity, require_organization_access
from ..dependencies.costs import get_cost_service
from ..services.costs import CostService

router = APIRouter(tags=["costs"])


def _cost_query(
    agentId: str | None = Query(default=None),
    projectId: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    biller: str | None = Query(default=None),
    model: str | None = Query(default=None),
    startTime: str | None = Query(default=None),
    endTime: str | None = Query(default=None),
    limit: int = Query(default=100),
) -> CostQuery:
    try:
        return validate_cost_query(
            {
                "agentId": agentId,
                "projectId": projectId,
                "provider": provider,
                "biller": biller,
                "model": model,
                "startTime": startTime,
                "endTime": endTime,
                "limit": limit,
            }
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(ORG_COST_EVENT_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_cost_event_route(
    orgId: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: CostService = Depends(get_cost_service),
) -> CostEvent:
    actor = require_actor_identity(request)
    try:
        payload = validate_create_cost_event(body)
        return await service.create_event(
            orgId,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get(ORG_COST_SUMMARY_PATH)
async def cost_summary_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    query: CostQuery = Depends(_cost_query),
    service: CostService = Depends(get_cost_service),
) -> CostSummary:
    return await service.summary(orgId, query)


@router.get(ORG_COST_BY_AGENT_PATH)
async def cost_by_agent_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    query: CostQuery = Depends(_cost_query),
    service: CostService = Depends(get_cost_service),
) -> list[CostDimensionRow]:
    return await service.by_agent(orgId, query)


@router.get(ORG_COST_BY_PROVIDER_PATH)
async def cost_by_provider_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    query: CostQuery = Depends(_cost_query),
    service: CostService = Depends(get_cost_service),
) -> list[CostDimensionRow]:
    return await service.by_provider(orgId, query)


@router.get(ORG_COST_BY_BILLER_PATH)
async def cost_by_biller_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    query: CostQuery = Depends(_cost_query),
    service: CostService = Depends(get_cost_service),
) -> list[CostDimensionRow]:
    return await service.by_biller(orgId, query)


@router.get(ORG_COST_BY_PROJECT_PATH)
async def cost_by_project_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    query: CostQuery = Depends(_cost_query),
    service: CostService = Depends(get_cost_service),
) -> list[CostDimensionRow]:
    return await service.by_project(orgId, query)


@router.get(ORG_COST_BY_AGENT_MODEL_PATH)
async def cost_by_agent_model_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    query: CostQuery = Depends(_cost_query),
    service: CostService = Depends(get_cost_service),
) -> list[CostDimensionRow]:
    return await service.by_agent_model(orgId, query)


@router.get(ORG_COST_TREND_PATH)
async def cost_trend_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    query: CostQuery = Depends(_cost_query),
    service: CostService = Depends(get_cost_service),
) -> list[CostTrendRow]:
    return await service.trend(orgId, query)


@router.get(ORG_COST_WINDOW_SPEND_PATH)
async def cost_window_spend_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    query: CostQuery = Depends(_cost_query),
    service: CostService = Depends(get_cost_service),
) -> CostWindowSpend:
    return await service.window_spend(orgId, query)
