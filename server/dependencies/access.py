from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class ActorIdentity:
    actor_type: str
    actor_id: str
    org_id: str | None = None
    run_id: str | None = None


def _actor_value(actor: object, key: str) -> Any:
    if isinstance(actor, Mapping):
        return actor.get(key)
    return getattr(actor, key, None)


def require_actor_identity(request: Request) -> ActorIdentity:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Actor context is not configured",
        )

    actor_type = _actor_value(actor, "type") or _actor_value(actor, "kind")
    actor_id = (
        _actor_value(actor, "userId")
        or _actor_value(actor, "id")
        or _actor_value(actor, "agentId")
    )
    if not actor_type or not actor_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Actor context is incomplete",
        )
    return ActorIdentity(
        actor_type=str(actor_type),
        actor_id=str(actor_id),
        org_id=(
            str(_actor_value(actor, "orgId"))
            if _actor_value(actor, "orgId") is not None
            else None
        ),
        run_id=(
            str(_actor_value(actor, "runId"))
            if _actor_value(actor, "runId") is not None
            else None
        ),
    )


def require_board_access(request: Request) -> None:
    if getattr(request.state, "actor", None) is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Actor context is not configured for board-scoped org listing",
        )
    actor = require_actor_identity(request)
    if actor.actor_type == "board":
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Board access required",
    )


def assert_organization_access(request: Request, org_id: str) -> None:
    actor = require_actor_identity(request)
    if actor.actor_type == "board":
        return
    if actor.actor_type == "agent" and actor.org_id == org_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Actor cannot access another organization",
    )


def require_organization_access(orgId: str, request: Request) -> None:
    assert_organization_access(request, orgId)
