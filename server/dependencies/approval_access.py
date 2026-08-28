from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.types.approval import ApprovalDetail
from server.access import AccessDeniedError, AccessPolicyService, AccessScopeResolver
from server.identity import IdentityContext

from .access import require_actor_identity
from .approvals import get_approval_service
from .database import get_session
from ..services.approvals import ApprovalService


@dataclass(frozen=True, slots=True)
class ApprovalOrganizationAccess:
    approval: ApprovalDetail
    context: IdentityContext


class ApprovalAccessScopeResolver(AccessScopeResolver[ApprovalDetail]):
    def __init__(self, session: AsyncSession, service: ApprovalService) -> None:
        super().__init__(session)
        self._service = service

    async def load(self, resource_id: str) -> ApprovalDetail | None:
        return await self._service.get_by_id(resource_id)

    def organization_id(self, resource: ApprovalDetail) -> str:
        return resource["orgId"]


async def get_approval_organization_access(
    id: str,
    request: Request,
    service: ApprovalService = Depends(get_approval_service),
    session: AsyncSession = Depends(get_session),
) -> ApprovalOrganizationAccess:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    source = (
        str(raw_actor.get("source") or "unknown")
        if isinstance(raw_actor, dict)
        else "unknown"
    )
    try:
        resolved = await ApprovalAccessScopeResolver(session, service).resolve(
            id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            source=source,
            run_id=actor.run_id,
        )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal cannot access this approval's organization",
        ) from exc
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval not found",
        )
    return ApprovalOrganizationAccess(
        approval=resolved.resource, context=resolved.context
    )


def require_approval_decision_access(
    access: ApprovalOrganizationAccess = Depends(get_approval_organization_access),
) -> ApprovalOrganizationAccess:
    try:
        AccessPolicyService().require_permission(
            access.context,
            access.approval["orgId"],
            "approvals:decide",
        )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing organization permission: approvals:decide",
        ) from exc
    return access
