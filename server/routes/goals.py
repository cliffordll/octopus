from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from packages.shared.api_paths.goals import (
    GOAL_DEPENDENCIES_PATH,
    GOAL_DETAIL_PATH,
    ORG_GOAL_LIST_PATH,
)
from packages.shared.types.goal import Goal, GoalDependencies
from packages.shared.validators.goal import validate_create_goal, validate_update_goal

from ..dependencies.access import (
    assert_organization_access,
    require_actor_identity,
    require_organization_access,
)
from ..dependencies.goals import get_goal_service
from ..services.goals import GoalConflictError, GoalService

router = APIRouter(tags=["goals"])


async def _goal_or_404(goal_id: str, *, request: Request, service: GoalService) -> Goal:
    goal = await service.get(goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found"
        )
    assert_organization_access(request, goal["orgId"])
    return goal


@router.get(ORG_GOAL_LIST_PATH)
async def list_goals_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    service: GoalService = Depends(get_goal_service),
) -> list[Goal]:
    return await service.list_for_org(orgId)


@router.post(ORG_GOAL_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_goal_route(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: GoalService = Depends(get_goal_service),
) -> Goal:
    try:
        payload = validate_create_goal(body)
        actor = require_actor_identity(request)
        return await service.create(
            orgId, payload, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get(GOAL_DETAIL_PATH)
async def get_goal_route(
    id: str,
    request: Request,
    service: GoalService = Depends(get_goal_service),
) -> Goal:
    return await _goal_or_404(id, request=request, service=service)


@router.get(GOAL_DEPENDENCIES_PATH)
async def get_goal_dependencies_route(
    id: str,
    request: Request,
    service: GoalService = Depends(get_goal_service),
) -> GoalDependencies:
    goal = await _goal_or_404(id, request=request, service=service)
    return await service.dependencies(goal)


@router.patch(GOAL_DETAIL_PATH)
async def update_goal_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    service: GoalService = Depends(get_goal_service),
) -> Goal:
    await _goal_or_404(id, request=request, service=service)
    try:
        payload = validate_update_goal(body)
        actor = require_actor_identity(request)
        updated = await service.update(
            id, payload, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found"
        )
    return updated


@router.delete(GOAL_DETAIL_PATH)
async def delete_goal_route(
    id: str,
    request: Request,
    service: GoalService = Depends(get_goal_service),
) -> Goal:
    await _goal_or_404(id, request=request, service=service)
    actor = require_actor_identity(request)
    try:
        removed = await service.remove(
            id, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except GoalConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": str(exc), "dependencies": exc.dependencies},
        ) from exc
    if removed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found"
        )
    return removed
