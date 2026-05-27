from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from packages.shared.api_paths.issues import ORG_ISSUE_LIST_MISSING_ORG_PATH
from packages.shared.api_paths.organizations import ORG_DETAIL_PATH, ORG_LIST_PATH
from packages.shared.types.organization import OrganizationDetail, OrganizationSummary
from packages.shared.validators.organization import (
    validate_create_organization,
    validate_update_organization,
)

from ..dependencies.access import require_actor_identity, require_board_access
from ..dependencies.orgs import get_org_detail, get_org_service
from ..services.orgs import OrgService

router = APIRouter(tags=["orgs"])


@router.get(ORG_LIST_PATH)
async def list_orgs(
    _: None = Depends(require_board_access),
    service: OrgService = Depends(get_org_service),
) -> list[OrganizationSummary]:
    return await service.list()


@router.post(ORG_LIST_PATH)
async def create_org(
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    service: OrgService = Depends(get_org_service),
) -> OrganizationDetail:
    try:
        payload = validate_create_organization(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    actor = require_actor_identity(request)
    return await service.create(
        payload,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )


@router.get(ORG_ISSUE_LIST_MISSING_ORG_PATH)
async def list_org_issues_missing_org_route() -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Missing orgId in path. Use /api/orgs/{orgId}/issues.",
    )


@router.get(ORG_DETAIL_PATH)
async def get_org(
    _: None = Depends(require_board_access),
    org: OrganizationDetail = Depends(get_org_detail),
) -> OrganizationDetail:
    return org


@router.patch(ORG_DETAIL_PATH)
async def update_org(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    org: OrganizationDetail = Depends(get_org_detail),
    service: OrgService = Depends(get_org_service),
) -> OrganizationDetail:
    try:
        payload = validate_update_organization(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    actor = require_actor_identity(request)
    updated = await service.update(
        orgId,
        payload,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return updated
