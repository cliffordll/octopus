from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.constants.access import PermissionKey
from server.access import AccessDeniedError, AccessPolicyService
from server.identity import IdentityContext
from server.identity.resolver import IdentityContextResolver

from .database import get_session


@dataclass(frozen=True)
class ActorIdentity:
    actor_type: str
    actor_id: str
    org_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class ActorOrganizationScope:
    organization_ids: tuple[str, ...]
    can_access_all: bool = False


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


def require_root_access(request: Request) -> None:
    if getattr(request.state, "actor", None) is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Actor context is not configured for root access",
        )
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    if actor.actor_type == "user" and bool(_actor_value(raw_actor, "isRoot")):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Root access required",
    )


def require_human_access(request: Request) -> None:
    actor = require_actor_identity(request)
    if actor.actor_type == "user":
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Human access required",
    )


def require_actor_organization_scope(request: Request) -> ActorOrganizationScope:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    if actor.actor_type == "user" and bool(_actor_value(raw_actor, "isRoot")):
        return ActorOrganizationScope(organization_ids=(), can_access_all=True)

    org_ids = _actor_value(raw_actor, "orgIds")
    scoped_ids = (
        {str(org_id) for org_id in org_ids if org_id is not None}
        if isinstance(org_ids, (list, tuple, set))
        else set()
    )
    if actor.actor_type == "agent" and actor.org_id is not None:
        scoped_ids.add(actor.org_id)
    return ActorOrganizationScope(organization_ids=tuple(sorted(scoped_ids)))


def assert_organization_access(request: Request, org_id: str) -> None:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    if actor.actor_type == "user" and bool(_actor_value(raw_actor, "isRoot")):
        return
    org_ids = _actor_value(raw_actor, "orgIds")
    if isinstance(org_ids, (list, tuple, set)) and org_id in org_ids:
        return
    if actor.actor_type == "agent" and actor.org_id == org_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Actor cannot access another organization",
    )


async def require_organization_access(
    orgId: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> IdentityContext:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    source = (
        str(raw_actor.get("source") or "unknown")
        if isinstance(raw_actor, Mapping)
        else "unknown"
    )
    context = await IdentityContextResolver(session).resolve(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        org_id=orgId,
        source=source,
        run_id=actor.run_id,
    )
    try:
        AccessPolicyService().require_organization_access(context, orgId)
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal cannot access this organization",
        ) from exc
    return context


async def assert_organization_permission(
    request: Request,
    session: AsyncSession,
    org_id: str,
    permission: PermissionKey,
) -> IdentityContext:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    source = (
        str(raw_actor.get("source") or "unknown")
        if isinstance(raw_actor, Mapping)
        else "unknown"
    )
    context = await IdentityContextResolver(session).resolve(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        org_id=org_id,
        source=source,
        run_id=actor.run_id,
    )
    try:
        AccessPolicyService().require_permission(context, org_id, permission)
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing organization permission: {permission}",
        ) from exc
    return context
