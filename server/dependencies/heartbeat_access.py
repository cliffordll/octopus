from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.types.heartbeat import HeartbeatRun
from server.access import AccessDeniedError, AccessPolicyService, AccessScopeResolver
from server.identity import IdentityContext
from server.services.heartbeat import HeartbeatService

from .access import require_actor_identity
from .database import get_session
from .heartbeat import get_heartbeat_service


@dataclass(frozen=True, slots=True)
class HeartbeatRunOrganizationAccess:
    run: HeartbeatRun
    context: IdentityContext


class HeartbeatRunAccessScopeResolver(AccessScopeResolver[HeartbeatRun]):
    def __init__(self, session: AsyncSession, service: HeartbeatService) -> None:
        super().__init__(session)
        self._service = service

    async def load(self, resource_id: str) -> HeartbeatRun | None:
        return await self._service.get(resource_id)

    def organization_id(self, resource: HeartbeatRun) -> str:
        return resource["orgId"]


async def require_heartbeat_run_manage(
    runId: str,
    request: Request,
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
    session: AsyncSession = Depends(get_session),
) -> HeartbeatRunOrganizationAccess:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    source = (
        str(raw_actor.get("source") or "unknown")
        if isinstance(raw_actor, dict)
        else "unknown"
    )
    try:
        resolved = await HeartbeatRunAccessScopeResolver(session, heartbeat).resolve(
            runId,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            source=source,
            run_id=actor.run_id,
        )
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Heartbeat run not found",
            )
        AccessPolicyService().require_permission(
            resolved.context,
            resolved.resource["orgId"],
            "agents:manage",
        )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing organization permission: agents:manage",
        ) from exc
    return HeartbeatRunOrganizationAccess(
        run=resolved.resource,
        context=resolved.context,
    )
