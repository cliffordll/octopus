from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.auth import (
    create_account,
    get_password_account,
    get_user_by_email,
)
from packages.database.queries.users import ensure_user

from .passwords import PasswordHasher
from .session import SessionAuth


class LocalPasswordAuth:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._passwords = PasswordHasher()
        self._sessions = SessionAuth(session)

    async def register(
        self,
        *,
        name: str,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str]:
        normalized_email = email.strip().lower()
        if not normalized_email or await get_user_by_email(
            self._session, normalized_email
        ):
            raise ValueError("Email is already registered")
        now = datetime.now(UTC)
        user_id = str(uuid.uuid4())
        await ensure_user(
            self._session,
            {
                "id": user_id,
                "name": name.strip(),
                "email": normalized_email,
                "email_verified": False,
                "created_at": now,
                "updated_at": now,
            },
        )
        await create_account(
            self._session,
            {
                "id": str(uuid.uuid4()),
                "account_id": normalized_email,
                "provider_id": "credential",
                "user_id": user_id,
                "password": self._passwords.hash(password),
                "created_at": now,
                "updated_at": now,
            },
        )
        return user_id, await self._sessions.create(
            user_id, ip_address=ip_address, user_agent=user_agent
        )

    async def sign_in(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str]:
        account = await get_password_account(self._session, email.strip().lower())
        if (
            account is None
            or account.password is None
            or not self._passwords.verify(password, account.password)
        ):
            raise ValueError("Invalid email or password")
        return account.user_id, await self._sessions.create(
            account.user_id, ip_address=ip_address, user_agent=user_agent
        )
