from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Depends, HTTPException, Request, status

from packages.shared.api_paths.organizations import ORG_LIST_PATH
from packages.shared.types.organization import OrganizationSummary

from ..dependencies.orgs import get_org_service
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


@router.get(ORG_LIST_PATH)
async def list_orgs(
    _: None = Depends(require_board_access),
    service: OrgService = Depends(get_org_service),
) -> list[OrganizationSummary]:
    return await service.list()
