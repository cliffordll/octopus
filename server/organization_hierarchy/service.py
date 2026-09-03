from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.agents import update_agent
from packages.database.queries.roles import get_role_by_id, update_role
from packages.database.schema import Role
from server.roles.directory import RoleDirectoryEntry, RoleDirectoryService


@dataclass(frozen=True, slots=True)
class HierarchyMember:
    role: Role
    display_name: str
    reports_to: str | None


class OrganizationHierarchyService:
    """Owns reporting relationships between Human and Agent organization members."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._directory = RoleDirectoryService(session)

    async def list(self, org_id: str) -> list[HierarchyMember]:
        entries = await self._directory.list_organization(org_id)
        owner = self._primary_owner(entries)
        return [
            HierarchyMember(
                role=entry.role,
                display_name=entry.display_name,
                reports_to=self._effective_manager(entry.role, owner),
            )
            for entry in entries
        ]

    async def assign_default(self, org_id: str, member_id: str) -> HierarchyMember:
        return await self.set_manager(org_id, member_id, None)

    async def set_manager(
        self, org_id: str, member_id: str, manager_id: str | None
    ) -> HierarchyMember:
        member = await self._organization_role(org_id, member_id)
        if member.role == "owner":
            if manager_id is not None:
                raise ValueError("Organization owners cannot report to another member")
            return await self._describe(member, None)

        manager = (
            await self._organization_role(org_id, manager_id)
            if manager_id is not None
            else await self._default_owner(org_id)
        )
        if member.status != "active" or (
            manager is not None and manager.status != "active"
        ):
            raise ValueError("Reporting relationships require active members")
        if manager is None:
            updated = await update_role(
                self._session,
                member.id,
                {"reports_to": None, "updated_at": datetime.now(UTC)},
            )
            if updated is None:
                raise RuntimeError("Organization member disappeared during update")
            await self._mirror_agent_relationship(updated, None)
            return await self._describe(updated, None)
        if member.id == manager.id:
            raise ValueError("A member cannot report to itself")
        await self._validate_no_cycle(org_id, member.id, manager.id)
        updated = await update_role(
            self._session,
            member.id,
            {"reports_to": manager.id, "updated_at": datetime.now(UTC)},
        )
        if updated is None:
            raise RuntimeError("Organization member disappeared during update")
        await self._mirror_agent_relationship(updated, manager)
        return await self._describe(updated, manager.id)

    async def _organization_role(self, org_id: str, role_id: str) -> Role:
        role = await get_role_by_id(
            self._session,
            scope_type="organization",
            scope_id=org_id,
            role_id=role_id,
        )
        if role is None:
            raise ValueError("Organization member not found")
        return role

    async def _default_owner(self, org_id: str) -> Role | None:
        entries = await self._directory.list_organization(org_id)
        owner = self._primary_owner(entries)
        return owner.role if owner is not None else None

    @staticmethod
    def _primary_owner(entries: list[RoleDirectoryEntry]) -> RoleDirectoryEntry | None:
        owners = [
            entry
            for entry in entries
            if entry.role.role == "owner" and entry.role.status == "active"
        ]
        return min(
            owners,
            key=lambda entry: (entry.role.created_at, entry.role.id),
            default=None,
        )

    @staticmethod
    def _effective_manager(role: Role, owner: RoleDirectoryEntry | None) -> str | None:
        if role.role == "owner":
            return None
        return role.reports_to or (owner.role.id if owner is not None else None)

    async def _validate_no_cycle(
        self, org_id: str, member_id: str, manager_id: str
    ) -> None:
        current_id: str | None = manager_id
        visited: set[str] = set()
        while current_id is not None:
            if current_id == member_id:
                raise ValueError("Reporting relationship would create a cycle")
            if current_id in visited:
                raise ValueError("Existing reporting relationship contains a cycle")
            visited.add(current_id)
            current = await self._organization_role(org_id, current_id)
            current_id = current.reports_to

    async def _mirror_agent_relationship(
        self, member: Role, manager: Role | None
    ) -> None:
        if member.principal_type != "agent":
            return
        manager_agent_id = (
            manager.principal_id
            if manager is not None and manager.principal_type == "agent"
            else None
        )
        await update_agent(
            self._session,
            member.principal_id,
            {"reports_to": manager_agent_id},
        )

    async def _describe(self, role: Role, reports_to: str | None) -> HierarchyMember:
        entry = await self._directory.describe(role)
        return HierarchyMember(
            role=entry.role,
            display_name=entry.display_name,
            reports_to=reports_to,
        )
