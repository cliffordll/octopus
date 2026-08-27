from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.access import AccessDeniedError, AccessPolicyService
from server.identity import IdentityContext, IdentityContextResolver

from .access import require_actor_identity
from .database import get_session


async def get_identity_context(
    request: Request,
    orgId: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> IdentityContext:
    actor = require_actor_identity(request)
    if orgId is not None and actor.org_id is not None and actor.org_id != orgId:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated identity cannot access another organization",
        )
    source = "unknown"
    raw_actor = getattr(request.state, "actor", None)
    if isinstance(raw_actor, dict):
        source = str(raw_actor.get("source") or source)
    return await IdentityContextResolver(session).resolve(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        org_id=orgId or actor.org_id,
        source=source,
        run_id=actor.run_id,
    )


def require_context_organization_access(
    orgId: str,
    context: IdentityContext = Depends(get_identity_context),
) -> IdentityContext:
    try:
        AccessPolicyService().require_organization_access(context, orgId)
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal cannot access this organization",
        ) from exc
    return context
