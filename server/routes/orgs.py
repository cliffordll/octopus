from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from packages.shared.api_paths.organizations import ORG_DETAIL_PATH, ORG_LIST_PATH
from packages.shared.types.organization import OrganizationDetail, OrganizationSummary
from packages.shared.validators.organization import validate_update_organization

from ..dependencies.orgs import get_org_service, get_owned_org_detail
from ..services.orgs import OrgService

router = APIRouter(tags=["orgs"])


def require_board_access(request: Request) -> None:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Actor context is not configured for board-scoped org listing",
        )

    actor_type = None
    actor_kind = None
    actor_role = None
    if isinstance(actor, Mapping):
        actor_type = actor.get("type")
        actor_kind = actor.get("kind")
        actor_role = actor.get("role")
    else:
        actor_type = getattr(actor, "type", None)
        actor_kind = getattr(actor, "kind", None)
        actor_role = getattr(actor, "role", None)

    if actor_type == "board" or actor_kind == "board" or actor_role == "board":
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Board access required",
    )


def _extract_actor_identity(request: Request) -> tuple[str, str]:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        return "system", "board"

    if isinstance(actor, Mapping):
        actor_type = actor.get("type") or actor.get("kind") or "system"
        actor_id = (
            actor.get("userId") or actor.get("id") or actor.get("agentId") or "board"
        )
    else:
        actor_type = (
            getattr(actor, "type", None) or getattr(actor, "kind", None) or "system"
        )
        actor_id = (
            getattr(actor, "userId", None)
            or getattr(actor, "id", None)
            or getattr(actor, "agentId", None)
            or "board"
        )

    return str(actor_type), str(actor_id)


@router.get(ORG_LIST_PATH)
async def list_orgs(
    _: None = Depends(require_board_access),
    service: OrgService = Depends(get_org_service),
) -> list[OrganizationSummary]:
    return await service.list()


@router.get(ORG_DETAIL_PATH)
async def get_org(
    org: OrganizationDetail = Depends(get_owned_org_detail),
) -> OrganizationDetail:
    return org


@router.patch(ORG_DETAIL_PATH)
async def update_org(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    org: OrganizationDetail = Depends(get_owned_org_detail),
    service: OrgService = Depends(get_org_service),
) -> OrganizationDetail:
    try:
        payload = validate_update_organization(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    actor_type, actor_id = _extract_actor_identity(request)
    updated = await service.update(
        orgId,
        payload,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return updated
