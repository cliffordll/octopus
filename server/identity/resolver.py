from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.constants.access import INSTANCE_SCOPE_ID
from server.access import PermissionService
from server.roles import RoleAccessService, RoleService

from .context import IdentityContext
from .principal import PrincipalRef


class IdentityContextResolver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._role_access = RoleAccessService(RoleService(session))
        self._permissions = PermissionService(session)

    async def resolve(
        self,
        *,
        actor_type: str,
        actor_id: str,
        org_id: str | None,
        source: str,
        run_id: str | None = None,
    ) -> IdentityContext:
        principal = PrincipalRef.from_actor(actor_type, actor_id)
        if principal.type == "system":
            raise ValueError(
                "System request contexts must use SystemIdentityContextFactory"
            )

        role = None
        permissions = []
        if org_id is not None:
            role = await self._role_access.find_active(
                "organization", org_id, principal
            )
            permissions = await self._permissions.list(
                "organization", org_id, principal
            )

        root_role = await self._role_access.find_active(
            "instance", INSTANCE_SCOPE_ID, principal
        )
        return IdentityContext(
            principal=principal,
            org_id=org_id,
            role_id=role.id if role is not None else None,
            role=role.role if role is not None else None,
            permissions=frozenset(item.permission_key for item in permissions),
            permission_constraints={
                item.permission_key: item.constraints for item in permissions
            },
            source=source,
            run_id=run_id,
            is_root=root_role is not None and root_role.role == "root",
        )
