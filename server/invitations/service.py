from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.invites import (
    create_invite,
    claim_invite,
    get_invite_by_id,
    get_invite_by_token_hash,
    list_org_invites,
    update_invite,
)
from packages.database.schema import Invite
from server.identity import PrincipalRef
from server.organization_hierarchy import OrganizationHierarchyService
from server.roles import RoleService


class InvitationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._roles = RoleService(session)
        self._hierarchy = OrganizationHierarchyService(session)

    async def create(
        self,
        org_id: str,
        *,
        allowed_join_types: str,
        defaults_payload: dict | None,
        invited_by_user_id: str | None,
    ) -> tuple[Invite, str]:
        if allowed_join_types not in {"human", "agent", "both"}:
            raise ValueError("Unsupported invite join type")
        token = secrets.token_urlsafe(32)
        row = await create_invite(
            self._session,
            {
                "org_id": org_id,
                "invite_type": "company_join",
                "token_hash": _hash_token(token),
                "allowed_join_types": allowed_join_types,
                "defaults_payload": defaults_payload,
                "expires_at": datetime.now(UTC) + timedelta(days=7),
                "invited_by_user_id": invited_by_user_id,
            },
        )
        return row, token

    async def list(self, org_id: str) -> list[Invite]:
        return list(await list_org_invites(self._session, org_id))

    async def inspect(self, token: str) -> Invite | None:
        return await get_invite_by_token_hash(self._session, _hash_token(token))

    async def accept_human(self, token: str, user_id: str) -> Invite:
        row = await self.inspect(token)
        now = datetime.now(UTC)
        if row is None:
            raise ValueError("Invite not found")
        expires_at = (
            row.expires_at
            if row.expires_at.tzinfo
            else row.expires_at.replace(tzinfo=UTC)
        )
        if row.revoked_at is not None or expires_at <= now:
            raise ValueError("Invite is no longer active")
        if row.org_id is None or row.allowed_join_types not in {"human", "both"}:
            raise ValueError("Invite does not allow human members")
        claimed = await claim_invite(
            self._session,
            row.id,
            user_id=user_id,
            accepted_at=now,
        )
        if claimed is None:
            await self._session.refresh(row)
            if row.accepted_by_user_id != user_id:
                raise ValueError("Invite was already accepted")
            return row
        role = await self._roles.ensure(
            "organization",
            row.org_id,
            PrincipalRef(type="user", id=user_id),
            role="member",
            status="active",
        )
        await self._hierarchy.assign_default(row.org_id, role.id)
        return claimed

    async def revoke(self, org_id: str, invite_id: str) -> Invite | None:
        row = await get_invite_by_id(self._session, invite_id)
        if row is None or row.org_id != org_id:
            return None
        now = datetime.now(UTC)
        return await update_invite(
            self._session, invite_id, {"revoked_at": now, "updated_at": now}
        )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
