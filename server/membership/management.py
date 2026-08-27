from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.organization_memberships import get_org_membership_by_id
from packages.database.schema import OrgMembership
from server.access import PermissionGrantSpec, PrincipalGrantService
from server.identity import PrincipalRef
from server.identity.principal import MembershipPrincipalType

from .service import MemberService


class MemberManagementService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._members = MemberService(session)
        self._grants = PrincipalGrantService(session)

    async def list(self, org_id: str) -> list[OrgMembership]:
        return await self._members.list(org_id)

    async def replace_permissions(
        self,
        org_id: str,
        member_id: str,
        grants: list[PermissionGrantSpec],
        *,
        granted_by_user_id: str | None,
    ) -> OrgMembership | None:
        member = await get_org_membership_by_id(self._session, org_id, member_id)
        if member is None:
            return None
        await self._grants.replace(
            org_id,
            PrincipalRef(
                type=cast(MembershipPrincipalType, member.principal_type),
                id=member.principal_id,
            ),
            grants,
            granted_by_user_id=granted_by_user_id,
        )
        return member
