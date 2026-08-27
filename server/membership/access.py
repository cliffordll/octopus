from __future__ import annotations

from packages.database.schema import OrgMembership
from server.access.errors import MembershipRequiredError
from server.identity.principal import PrincipalRef

from .service import MemberService


class MemberAccessService:
    def __init__(self, members: MemberService) -> None:
        self._members = members

    async def find_active(
        self, org_id: str, principal: PrincipalRef
    ) -> OrgMembership | None:
        if principal.type == "system":
            return None
        membership = await self._members.get(org_id, principal)
        if membership is None or membership.status != "active":
            return None
        return membership

    async def require_active(
        self, org_id: str, principal: PrincipalRef
    ) -> OrgMembership:
        membership = await self.find_active(org_id, principal)
        if membership is None:
            raise MembershipRequiredError(
                "Principal does not have an active organization membership"
            )
        return membership
