from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.agents import get_agent_by_id
from packages.database.queries.roles import get_role_by_id, update_role
from packages.database.queries.users import get_user_by_id
from packages.database.schema import Role
from packages.shared.constants.access import AccessScopeType
from server.access import PermissionService, PermissionSpec
from server.identity import PrincipalRef
from server.identity.principal import AccessPrincipalType

from .service import RoleService


@dataclass(frozen=True, slots=True)
class ManagedRole:
    role: Role
    display_name: str
    permissions: tuple[dict[str, Any], ...]


class RoleManagementService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._roles = RoleService(session)
        self._permissions = PermissionService(session)

    async def list_organization(self, org_id: str) -> list[ManagedRole]:
        rows = await self._roles.list("organization", org_id)
        return [await self._describe(row) for row in rows]

    async def replace_permissions(
        self,
        org_id: str,
        role_id: str,
        permissions: list[PermissionSpec],
        *,
        granted_by_user_id: str | None,
    ) -> ManagedRole | None:
        role = await get_role_by_id(
            self._session,
            scope_type="organization",
            scope_id=org_id,
            role_id=role_id,
        )
        if role is None:
            return None
        await self._permissions.replace(
            "organization",
            org_id,
            PrincipalRef(
                type=cast(AccessPrincipalType, role.principal_type),
                id=role.principal_id,
            ),
            permissions,
            granted_by_user_id=granted_by_user_id,
        )
        return await self._describe(role)

    async def update_status(
        self, org_id: str, role_id: str, status: str
    ) -> ManagedRole | None:
        if status not in {"active", "suspended"}:
            raise ValueError("Role status must be active or suspended")
        role = await get_role_by_id(
            self._session,
            scope_type="organization",
            scope_id=org_id,
            role_id=role_id,
        )
        if role is None:
            return None
        if role.role == "owner":
            raise ValueError("Organization owners cannot be suspended")
        updated = await update_role(self._session, role.id, {"status": status})
        return await self._describe(updated) if updated is not None else None

    async def _describe(self, role: Role) -> ManagedRole:
        principal = PrincipalRef(
            type=cast(AccessPrincipalType, role.principal_type),
            id=role.principal_id,
        )
        permissions = await self._permissions.list(
            cast(AccessScopeType, role.scope_type), role.scope_id, principal
        )
        if principal.type == "user":
            user = await get_user_by_id(self._session, principal.id)
            display_name = user.name if user is not None else principal.id
        else:
            agent = await get_agent_by_id(self._session, principal.id)
            display_name = agent.name if agent is not None else principal.id
        return ManagedRole(
            role=role,
            display_name=display_name,
            permissions=tuple(
                {
                    "permissionKey": permission.permission_key,
                    "constraints": permission.constraints,
                }
                for permission in permissions
            ),
        )
