from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.types.issue import IssueDetail
from server.access import AccessDeniedError, AccessPolicyService, AccessScopeResolver
from server.identity import IdentityContext
from server.services.issues import IssueService

from .access import require_actor_identity
from .database import get_session
from .issues import get_issue_service


@dataclass(frozen=True, slots=True)
class IssueOrganizationAccess:
    issue: IssueDetail
    context: IdentityContext


class IssueAccessScopeResolver(AccessScopeResolver[IssueDetail]):
    def __init__(self, session: AsyncSession, service: IssueService) -> None:
        super().__init__(session)
        self._service = service

    async def load(self, resource_id: str) -> IssueDetail | None:
        return await self._service.get_by_id(resource_id)

    def organization_id(self, resource: IssueDetail) -> str:
        return resource["orgId"]


async def get_issue_organization_access(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
    session: AsyncSession = Depends(get_session),
) -> IssueOrganizationAccess:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    source = (
        str(raw_actor.get("source") or "unknown")
        if isinstance(raw_actor, dict)
        else "unknown"
    )
    try:
        resolved = await IssueAccessScopeResolver(session, service).resolve(
            id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            source=source,
            run_id=actor.run_id,
        )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal cannot access this issue's organization",
        ) from exc
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Issue not found"
        )
    return IssueOrganizationAccess(issue=resolved.resource, context=resolved.context)


def require_issue_documents_manage(
    access: IssueOrganizationAccess = Depends(get_issue_organization_access),
) -> IssueOrganizationAccess:
    try:
        AccessPolicyService().require_permission(
            access.context,
            access.issue["orgId"],
            "documents:manage",
        )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing organization permission: documents:manage",
        ) from exc
    return access


def require_issue_tasks_assign(
    access: IssueOrganizationAccess = Depends(get_issue_organization_access),
) -> IssueOrganizationAccess:
    try:
        AccessPolicyService().require_permission(
            access.context,
            access.issue["orgId"],
            "tasks:assign",
        )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing organization permission: tasks:assign",
        ) from exc
    return access
