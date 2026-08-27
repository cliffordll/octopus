from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.agents import get_agent_by_id
from packages.database.queries.organization_memberships import (
    ensure_org_membership_row,
    get_org_membership,
    list_org_memberships,
    update_org_membership,
)
from packages.database.queries.users import get_user_by_id
from packages.database.schema import OrgMembership
from packages.shared.constants.access import MEMBERSHIP_STATUSES, MembershipStatus
from server.identity.principal import PrincipalRef


class MemberService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, org_id: str, principal: PrincipalRef) -> OrgMembership | None:
        return await get_org_membership(
            self._session,
            org_id=org_id,
            principal_type=principal.membership_type(),
            principal_id=principal.id,
        )

    async def list(self, org_id: str) -> list[OrgMembership]:
        return list(await list_org_memberships(self._session, org_id))

    async def ensure(
        self,
        org_id: str,
        principal: PrincipalRef,
        *,
        role: str | None = "member",
        status: MembershipStatus = "active",
    ) -> OrgMembership:
        if status not in MEMBERSHIP_STATUSES:
            raise ValueError(f"Unsupported membership status: {status}")
        await self._validate_principal(org_id, principal)
        row = await ensure_org_membership_row(
            self._session,
            {
                "org_id": org_id,
                "principal_type": principal.membership_type(),
                "principal_id": principal.id,
                "status": status,
                "membership_role": role,
            },
        )
        if row.status == status and row.membership_role == role:
            return row
        updated = await update_org_membership(
            self._session,
            row.id,
            {
                "status": status,
                "membership_role": role,
                "updated_at": datetime.now(UTC),
            },
        )
        if updated is None:
            raise RuntimeError("Organization membership disappeared during update")
        return updated

    async def _validate_principal(self, org_id: str, principal: PrincipalRef) -> None:
        if principal.type == "user":
            if await get_user_by_id(self._session, principal.id) is None:
                raise ValueError("User principal does not exist")
            return
        if principal.type == "agent":
            agent = await get_agent_by_id(self._session, principal.id)
            if agent is None:
                raise ValueError("Agent principal does not exist")
            if agent.org_id != org_id:
                raise ValueError("Agent principal belongs to another organization")
            return
        principal.membership_type()
