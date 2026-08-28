from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.agents import get_agent_by_id
from packages.database.queries.roles import (
    ensure_role,
    get_role,
    list_scope_roles,
    update_role,
)
from packages.database.queries.users import get_user_by_id
from packages.database.schema import Role
from packages.shared.constants.access import (
    ACCESS_SCOPE_TYPES,
    INSTANCE_SCOPE_ID,
    ROLE_NAMES,
    ROLE_STATUSES,
    AccessScopeType,
    RoleName,
    RoleStatus,
)
from server.identity.principal import PrincipalRef


class RoleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        scope_type: AccessScopeType,
        scope_id: str,
        principal: PrincipalRef,
    ) -> Role | None:
        return await get_role(
            self._session,
            scope_type=scope_type,
            scope_id=scope_id,
            principal_type=principal.access_type(),
            principal_id=principal.id,
        )

    async def list(self, scope_type: AccessScopeType, scope_id: str) -> list[Role]:
        return list(
            await list_scope_roles(
                self._session, scope_type=scope_type, scope_id=scope_id
            )
        )

    async def ensure(
        self,
        scope_type: AccessScopeType,
        scope_id: str,
        principal: PrincipalRef,
        *,
        role: RoleName,
        status: RoleStatus = "active",
    ) -> Role:
        self._validate_values(scope_type, scope_id, principal, role, status)
        await self._validate_principal(scope_type, scope_id, principal)
        row = await ensure_role(
            self._session,
            {
                "scope_type": scope_type,
                "scope_id": scope_id,
                "principal_type": principal.access_type(),
                "principal_id": principal.id,
                "status": status,
                "role": role,
            },
        )
        if row.status == status and row.role == role:
            return row
        updated = await update_role(
            self._session,
            row.id,
            {
                "status": status,
                "role": role,
                "updated_at": datetime.now(UTC),
            },
        )
        if updated is None:
            raise RuntimeError("Role disappeared during update")
        return updated

    @staticmethod
    def _validate_values(
        scope_type: str,
        scope_id: str,
        principal: PrincipalRef,
        role: str,
        status: str,
    ) -> None:
        if scope_type not in ACCESS_SCOPE_TYPES:
            raise ValueError(f"Unsupported role scope: {scope_type}")
        if role not in ROLE_NAMES:
            raise ValueError(f"Unsupported role: {role}")
        if status not in ROLE_STATUSES:
            raise ValueError(f"Unsupported role status: {status}")
        if scope_type == "instance":
            if (
                scope_id != INSTANCE_SCOPE_ID
                or principal.type != "user"
                or role != "root"
            ):
                raise ValueError("Instance roles must grant root to a user")
        elif role == "root":
            raise ValueError("Root is only valid in the instance scope")

    async def _validate_principal(
        self, scope_type: AccessScopeType, scope_id: str, principal: PrincipalRef
    ) -> None:
        if principal.type == "user":
            if await get_user_by_id(self._session, principal.id) is None:
                raise ValueError("User principal does not exist")
            return
        if principal.type == "agent":
            agent = await get_agent_by_id(self._session, principal.id)
            if agent is None:
                raise ValueError("Agent principal does not exist")
            if scope_type == "instance":
                raise ValueError("Agents cannot have instance roles")
            if agent.org_id != scope_id:
                raise ValueError("Agent principal belongs to another organization")
            return
        principal.access_type()
