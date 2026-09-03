from __future__ import annotations

from packages.database.schema import Role
from packages.shared.constants.access import AccessScopeType
from server.access_errors import RoleRequiredError
from server.identity.principal import PrincipalRef

from .service import RoleService


class RoleAccessService:
    def __init__(self, roles: RoleService) -> None:
        self._roles = roles

    async def find_active(
        self,
        scope_type: AccessScopeType,
        scope_id: str,
        principal: PrincipalRef,
    ) -> Role | None:
        if principal.type == "system":
            return None
        role = await self._roles.get(scope_type, scope_id, principal)
        if role is None or role.status != "active":
            return None
        return role

    async def require_active(
        self,
        scope_type: AccessScopeType,
        scope_id: str,
        principal: PrincipalRef,
    ) -> Role:
        role = await self.find_active(scope_type, scope_id, principal)
        if role is None:
            raise RoleRequiredError(
                "Principal does not have an active role in this scope"
            )
        return role
