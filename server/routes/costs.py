from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from packages.shared.api_paths.costs import (
    AGENT_BUDGET_PATCH_PATH,
    ORG_BUDGET_INCIDENT_RESOLVE_PATH,
    ORG_BUDGET_OVERVIEW_PATH,
    ORG_BUDGET_PATCH_PATH,
    ORG_BUDGET_POLICY_LIST_PATH,
    ORG_COST_BY_AGENT_MODEL_PATH,
    ORG_COST_BY_AGENT_PATH,
    ORG_COST_BY_BILLER_PATH,
    ORG_COST_BY_PROJECT_PATH,
    ORG_COST_BY_PROVIDER_PATH,
    ORG_COST_EVENT_LIST_PATH,
    ORG_COST_QUOTA_WINDOWS_PATH,
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
from packages.shared.types.budget import (
    BudgetIncident,
    BudgetOverview,
    BudgetPolicySummary,
)
from packages.shared.validators.budget import (
    validate_budget_amount_patch,
    validate_resolve_budget_incident,
    validate_upsert_budget_policy,
)
from packages.shared.validators.cost import (
    validate_cost_query,
    validate_create_cost_event,
)

from ..dependencies.access import (
    assert_organization_access,
    require_actor_identity,
    require_organization_access,
)
from ..dependencies.budgets import get_budget_service
from ..dependencies.costs import get_cost_service
from ..services.budgets import BudgetService
from ..services.costs import CostService
from ..services.quota_windows import QuotaWindowService

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


@router.get(ORG_COST_QUOTA_WINDOWS_PATH)
async def cost_quota_windows_route(
    orgId: str,
    _: None = Depends(require_organization_access),
) -> dict[str, Any]:
    return await QuotaWindowService().fetch_org_quota_windows(orgId)


@router.get(ORG_BUDGET_OVERVIEW_PATH)
async def budget_overview_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetOverview:
    return await service.overview(orgId)


@router.post(ORG_BUDGET_POLICY_LIST_PATH)
async def upsert_budget_policy_route(
    orgId: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetPolicySummary:
    actor = require_actor_identity(request)
    try:
        payload = validate_upsert_budget_policy(body)
        return await service.upsert_policy(
            orgId,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(ORG_BUDGET_INCIDENT_RESOLVE_PATH)
async def resolve_budget_incident_route(
    orgId: str,
    incidentId: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetIncident:
    actor = require_actor_identity(request)
    try:
        payload = validate_resolve_budget_incident(body)
        return await service.resolve_incident(
            orgId,
            incidentId,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.patch(ORG_BUDGET_PATCH_PATH)
async def patch_org_budget_route(
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: BudgetService = Depends(get_budget_service),
) -> dict[str, int]:
    try:
        amount = validate_budget_amount_patch(body)
        return await service.update_org_budget(orgId, amount)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.patch(AGENT_BUDGET_PATCH_PATH)
async def patch_agent_budget_route(
    agentId: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: BudgetService = Depends(get_budget_service),
) -> dict[str, int]:
    try:
        amount = validate_budget_amount_patch(body)
        org_id = await service.get_agent_org_id(agentId)
        assert_organization_access(request, org_id)
        return await service.update_agent_budget(agentId, amount)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
