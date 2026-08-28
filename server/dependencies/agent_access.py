from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.types.agent import Agent
from server.access import AccessDeniedError, AccessPolicyService, AccessScopeResolver
from server.identity import IdentityContext

from .access import require_actor_identity
from .agents import get_agent_service
from .database import get_session
from ..services.agents import AgentService


@dataclass(frozen=True, slots=True)
class AgentOrganizationAccess:
    agent: Agent
    context: IdentityContext


class AgentAccessScopeResolver(AccessScopeResolver[Agent]):
    def __init__(self, session: AsyncSession, service: AgentService) -> None:
        super().__init__(session)
        self._service = service

    async def load(self, resource_id: str) -> Agent | None:
        return await self._service.get(resource_id)

    def organization_id(self, resource: Agent) -> str:
        return resource["orgId"]


async def get_agent_organization_access(
    id: str,
    request: Request,
    service: AgentService = Depends(get_agent_service),
    session: AsyncSession = Depends(get_session),
) -> AgentOrganizationAccess:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    source = (
        str(raw_actor.get("source") or "unknown")
        if isinstance(raw_actor, dict)
        else "unknown"
    )
    try:
        resolved = await AgentAccessScopeResolver(session, service).resolve(
            id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            source=source,
            run_id=actor.run_id,
        )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal cannot access this agent's organization",
        ) from exc
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return AgentOrganizationAccess(agent=resolved.resource, context=resolved.context)


def require_agent_skills_manage(
    access: AgentOrganizationAccess = Depends(get_agent_organization_access),
) -> AgentOrganizationAccess:
    try:
        AccessPolicyService().require_permission(
            access.context,
            access.agent["orgId"],
            "skills:manage",
        )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing organization permission: skills:manage",
        ) from exc
    return access


def require_agent_manage(
    access: AgentOrganizationAccess = Depends(get_agent_organization_access),
) -> AgentOrganizationAccess:
    try:
        AccessPolicyService().require_permission(
            access.context,
            access.agent["orgId"],
            "agents:manage",
        )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing organization permission: agents:manage",
        ) from exc
    return access
