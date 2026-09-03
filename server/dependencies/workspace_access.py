from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.types.issue_attachment import IssueAttachment
from packages.shared.types.workspace import ExecutionWorkspace, IssueWorkProduct
from server.access import AccessDeniedError, AccessPolicyService, AccessScopeResolver
from server.identity import IdentityContext
from server.services.issues import IssueService
from server.services.workspaces import WorkspaceService

from .access import require_actor_identity
from .database import get_session
from .issues import get_issue_service
from .workspaces import get_workspace_service


@dataclass(frozen=True, slots=True)
class WorkspaceResourceAccess:
    resource: IssueWorkProduct | IssueAttachment | ExecutionWorkspace
    context: IdentityContext


class WorkProductAccessScopeResolver(AccessScopeResolver[IssueWorkProduct]):
    def __init__(self, session: AsyncSession, service: WorkspaceService) -> None:
        super().__init__(session)
        self._service = service

    async def load(self, resource_id: str) -> IssueWorkProduct | None:
        return await self._service.get_work_product(resource_id)

    def organization_id(self, resource: IssueWorkProduct) -> str:
        return resource["orgId"]


class AttachmentAccessScopeResolver(AccessScopeResolver[IssueAttachment]):
    def __init__(self, session: AsyncSession, service: IssueService) -> None:
        super().__init__(session)
        self._service = service

    async def load(self, resource_id: str) -> IssueAttachment | None:
        return await self._service.get_attachment(resource_id)

    def organization_id(self, resource: IssueAttachment) -> str:
        return resource["orgId"]


class ExecutionWorkspaceAccessScopeResolver(AccessScopeResolver[ExecutionWorkspace]):
    def __init__(self, session: AsyncSession, service: WorkspaceService) -> None:
        super().__init__(session)
        self._service = service

    async def load(self, resource_id: str) -> ExecutionWorkspace | None:
        return await self._service.get_execution_workspace(resource_id)

    def organization_id(self, resource: ExecutionWorkspace) -> str:
        return resource["orgId"]


DocumentResourceT = TypeVar("DocumentResourceT", IssueWorkProduct, IssueAttachment)


async def _resolve_documents_manage(
    resolver: AccessScopeResolver[DocumentResourceT],
    resource_id: str,
    request: Request,
) -> WorkspaceResourceAccess:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    source = (
        str(raw_actor.get("source") or "unknown")
        if isinstance(raw_actor, dict)
        else "unknown"
    )
    try:
        resolved = await resolver.resolve(
            resource_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            source=source,
            run_id=actor.run_id,
        )
        if resolved is not None:
            AccessPolicyService().require_permission(
                resolved.context,
                resolver.organization_id(resolved.resource),
                "documents:manage",
            )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing organization permission: documents:manage",
        ) from exc
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return WorkspaceResourceAccess(resolved.resource, resolved.context)


async def require_work_product_documents_manage(
    id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResourceAccess:
    return await _resolve_documents_manage(
        WorkProductAccessScopeResolver(session, service), id, request
    )


async def require_attachment_documents_manage(
    attachmentId: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: IssueService = Depends(get_issue_service),
) -> WorkspaceResourceAccess:
    return await _resolve_documents_manage(
        AttachmentAccessScopeResolver(session, service), attachmentId, request
    )


async def require_execution_workspace_manage(
    workspaceId: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceResourceAccess:
    actor = require_actor_identity(request)
    raw_actor = getattr(request.state, "actor", None)
    source = (
        str(raw_actor.get("source") or "unknown")
        if isinstance(raw_actor, dict)
        else "unknown"
    )
    try:
        resolver = ExecutionWorkspaceAccessScopeResolver(session, service)
        resolved = await resolver.resolve(
            workspaceId,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            source=source,
            run_id=actor.run_id,
        )
        if resolved is not None:
            AccessPolicyService().require_permission(
                resolved.context,
                resolver.organization_id(resolved.resource),
                "workspaces:manage",
            )
    except AccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing organization permission: workspaces:manage",
        ) from exc
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution workspace not found",
        )
    return WorkspaceResourceAccess(resolved.resource, resolved.context)
