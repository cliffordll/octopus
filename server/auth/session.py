from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.auth import (
    create_auth_session,
    delete_session,
    get_session_with_user,
    touch_session,
)
from server.identity import PrincipalRef

from .contracts import AuthResult


class SessionAuth:
    def __init__(
        self, session: AsyncSession, *, ttl: timedelta = timedelta(days=7)
    ) -> None:
        self._session = session
        self._ttl = ttl

    async def create(
        self, user_id: str, *, ip_address: str | None, user_agent: str | None
    ) -> str:
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        await create_auth_session(
            self._session,
            {
                "id": str(uuid.uuid4()),
                "expires_at": now + self._ttl,
                "token": token,
                "created_at": now,
                "updated_at": now,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "user_id": user_id,
            },
        )
        return token

    async def authenticate(self, credential: str) -> AuthResult | None:
        row = await get_session_with_user(self._session, credential)
        if row is None:
            return None
        auth_session, user = row
        now = datetime.now(UTC)
        expires_at = auth_session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            await delete_session(self._session, credential)
            return None
        await touch_session(self._session, auth_session.id, now)
        return AuthResult(PrincipalRef(type="user", id=user.id), "session")

    async def revoke(self, credential: str) -> None:
        await delete_session(self._session, credential)
