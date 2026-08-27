from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.access import ensure_instance_user_role
from packages.database.queries.organizations import list_organizations
from packages.database.queries.users import ensure_user
from server.membership import MemberService

from .principal import PrincipalRef


LOCAL_BOARD_USER_ID = "local-board"


class LocalAccessBootstrapService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._members = MemberService(session)

    async def ensure(self) -> None:
        now = datetime.now(UTC)
        await ensure_user(
            self._session,
            {
                "id": LOCAL_BOARD_USER_ID,
                "name": "Local Board",
                "email": "local-board@localhost.invalid",
                "email_verified": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        await ensure_instance_user_role(
            self._session,
            user_id=LOCAL_BOARD_USER_ID,
            role="instance_admin",
        )
        for organization in await list_organizations(self._session):
            await self.ensure_org_owner(organization.id)

    async def ensure_org_owner(self, org_id: str) -> None:
        await self._members.ensure(
            org_id,
            PrincipalRef(type="user", id=LOCAL_BOARD_USER_ID),
            role="owner",
            status="active",
        )
