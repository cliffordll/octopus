from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.api_paths.access import (
    ORG_HIERARCHY_MANAGER_PATH,
    ORG_HIERARCHY_PATH,
)
from packages.shared.validators.access import validate_hierarchy_manager
from server.access import AccessDeniedError, AccessPolicyService
from server.dependencies.database import get_session
from server.dependencies.identity import get_identity_context
from server.identity import IdentityContext
from server.organization_hierarchy import HierarchyMember, OrganizationHierarchyService

router = APIRouter(tags=["organization-hierarchy"])


@router.get(ORG_HIERARCHY_PATH)
async def list_organization_hierarchy(
    orgId: str,
    context: IdentityContext = Depends(get_identity_context),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    try:
        AccessPolicyService().require_organization_access(context, orgId)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    members = await OrganizationHierarchyService(session).list(orgId)
    return [_hierarchy_member_response(member) for member in members]


@router.patch(ORG_HIERARCHY_MANAGER_PATH)
async def update_organization_manager(
    orgId: str,
    memberId: str,
    body: dict[str, Any] = Body(...),
    context: IdentityContext = Depends(get_identity_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        AccessPolicyService().require_permission(context, orgId, "organizations:manage")
        manager_id = validate_hierarchy_manager(body)
        member = await OrganizationHierarchyService(session).set_manager(
            orgId, memberId, manager_id
        )
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _hierarchy_member_response(member)


def _hierarchy_member_response(member: HierarchyMember) -> dict[str, Any]:
    role = member.role
    return {
        "id": role.id,
        "orgId": role.scope_id,
        "principalType": role.principal_type,
        "principalId": role.principal_id,
        "displayName": member.display_name,
        "status": role.status,
        "role": role.role,
        "reportsTo": member.reports_to,
    }
