from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.agents import get_agent_by_id
from packages.database.queries.users import get_user_by_id
from packages.database.schema import Role

from .service import RoleService


@dataclass(frozen=True, slots=True)
class RoleDirectoryEntry:
    role: Role
    display_name: str


class RoleDirectoryService:
    """Resolves access roles into organization member identities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._roles = RoleService(session)

    async def list_organization(self, org_id: str) -> list[RoleDirectoryEntry]:
        rows = await self._roles.list("organization", org_id)
        return [await self.describe(row) for row in rows]

    async def describe(self, role: Role) -> RoleDirectoryEntry:
        if role.principal_type == "user":
            user = await get_user_by_id(self._session, role.principal_id)
            display_name = user.name if user is not None else role.principal_id
        else:
            agent = await get_agent_by_id(self._session, role.principal_id)
            display_name = agent.name if agent is not None else role.principal_id
        return RoleDirectoryEntry(role=role, display_name=display_name)
