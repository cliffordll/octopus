from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.api_paths.access import (
    INVITE_ACCEPT_PATH,
    INVITE_DETAIL_PATH,
    ORG_INVITE_REVOKE_PATH,
    ORG_INVITES_PATH,
    ORG_MEMBER_PERMISSIONS_PATH,
    ORG_MEMBER_STATUS_PATH,
    ORG_MEMBERS_PATH,
)
from packages.shared.validators.access import (
    validate_create_invite,
    validate_member_grants,
)
from server.access import AccessDeniedError, AccessPolicyService, PermissionSpec
from server.dependencies.database import get_session
from server.dependencies.identity import get_identity_context
from server.identity import IdentityContext
from server.invitations import InvitationService
from server.roles.management import ManagedRole, RoleManagementService

router = APIRouter(tags=["access"])


@router.get(ORG_MEMBERS_PATH)
async def list_members(
    orgId: str,
    context: IdentityContext = Depends(get_identity_context),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    _require_permission(context, orgId, "users:manage_permissions")
    rows = await RoleManagementService(session).list_organization(orgId)
    return [_member_response(row) for row in rows]


@router.patch(ORG_MEMBER_PERMISSIONS_PATH)
async def update_member_permissions(
    orgId: str,
    memberId: str,
    body: dict[str, Any] = Body(...),
    context: IdentityContext = Depends(get_identity_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_permission(context, orgId, "users:manage_permissions")
    try:
        permissions = [
            PermissionSpec(
                permission=item["permissionKey"],
                constraints=item["constraints"],
            )
            for item in validate_member_grants(body)
        ]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = await RoleManagementService(session).replace_permissions(
        orgId,
        memberId,
        permissions,
        granted_by_user_id=context.principal.id
        if context.principal.type == "user"
        else None,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return _member_response(row)


@router.patch(ORG_MEMBER_STATUS_PATH)
async def update_member_status(
    orgId: str,
    memberId: str,
    body: dict[str, Any] = Body(...),
    context: IdentityContext = Depends(get_identity_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_permission(context, orgId, "users:manage_permissions")
    try:
        row = await RoleManagementService(session).update_status(
            orgId, memberId, str(body.get("status") or "")
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return _member_response(row)


@router.post(ORG_INVITES_PATH, status_code=201)
async def create_org_invite(
    orgId: str,
    body: dict[str, Any] = Body(...),
    context: IdentityContext = Depends(get_identity_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_permission(context, orgId, "users:invite")
    try:
        payload = validate_create_invite(body)
        row, token = await InvitationService(session).create(
            orgId,
            allowed_join_types=payload["allowedJoinTypes"],
            defaults_payload=payload["defaultsPayload"],
            invited_by_user_id=context.principal.id
            if context.principal.type == "user"
            else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**_invite_response(row), "token": token, "inviteUrl": f"/invite/{token}"}


@router.get(ORG_INVITES_PATH)
async def list_org_invites(
    orgId: str,
    context: IdentityContext = Depends(get_identity_context),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    _require_permission(context, orgId, "users:invite")
    return [
        _invite_response(row) for row in await InvitationService(session).list(orgId)
    ]


@router.post(ORG_INVITE_REVOKE_PATH)
async def revoke_org_invite(
    orgId: str,
    inviteId: str,
    context: IdentityContext = Depends(get_identity_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _require_permission(context, orgId, "users:invite")
    row = await InvitationService(session).revoke(orgId, inviteId)
    if row is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return _invite_response(row)


@router.get(INVITE_DETAIL_PATH)
async def inspect_invite(
    token: str, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    row = await InvitationService(session).inspect(token)
    if row is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    return _invite_response(row)


@router.post(INVITE_ACCEPT_PATH)
async def accept_invite(
    token: str,
    context: IdentityContext = Depends(get_identity_context),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if context.principal.type != "user":
        raise HTTPException(status_code=401, detail="Human authentication required")
    try:
        row = await InvitationService(session).accept_human(token, context.principal.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _invite_response(row)


def _require_permission(context: IdentityContext, org_id: str, permission: str) -> None:
    try:
        AccessPolicyService().require_permission(context, org_id, permission)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _member_response(managed: ManagedRole) -> dict[str, Any]:
    row = managed.role
    return {
        "id": row.id,
        "orgId": row.scope_id,
        "principalType": row.principal_type,
        "principalId": row.principal_id,
        "status": row.status,
        "role": row.role,
        "displayName": managed.display_name,
        "permissions": list(managed.permissions),
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }


def _invite_response(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "orgId": row.org_id,
        "inviteType": row.invite_type,
        "allowedJoinTypes": row.allowed_join_types,
        "defaultsPayload": row.defaults_payload,
        "expiresAt": row.expires_at.isoformat(),
        "invitedByUserId": row.invited_by_user_id,
        "revokedAt": row.revoked_at.isoformat() if row.revoked_at else None,
        "acceptedAt": row.accepted_at.isoformat() if row.accepted_at else None,
        "acceptedByUserId": row.accepted_by_user_id,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }
