from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.auth import (
    create_credential,
    get_password_credential,
    get_user_by_email,
)
from packages.database.queries.users import ensure_user
from packages.shared.constants.access import INSTANCE_SCOPE_ID
from server.identity import PrincipalRef
from server.roles import RoleService

from .passwords import PasswordHasher


class RootProvisioningService:
    """Provision the explicit instance root account for a fresh database."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._passwords = PasswordHasher()
        self._roles = RoleService(session)

    async def create(self, *, name: str, email: str, password: str) -> str:
        normalized_email = email.strip().lower()
        if not normalized_email or "@" not in normalized_email:
            raise ValueError("A valid email is required")
        if not name.strip():
            raise ValueError("Name is required")
        if len(password) < 8:
            raise ValueError("Password must contain at least 8 characters")
        existing = await get_user_by_email(self._session, normalized_email)
        if existing is not None:
            credential = await get_password_credential(self._session, normalized_email)
            if (
                credential is None
                or credential.password_hash is None
                or not self._passwords.verify(password, credential.password_hash)
            ):
                raise ValueError("Existing account password is invalid")
            await self._grant(existing.id)
            return existing.id

        now = datetime.now(UTC)
        user_id = str(uuid.uuid4())
        await ensure_user(
            self._session,
            {
                "id": user_id,
                "name": name.strip(),
                "email": normalized_email,
                "email_verified": True,
                "created_at": now,
                "updated_at": now,
            },
        )
        await create_credential(
            self._session,
            {
                "id": str(uuid.uuid4()),
                "account_id": normalized_email,
                "provider_id": "credential",
                "user_id": user_id,
                "password_hash": self._passwords.hash(password),
                "created_at": now,
                "updated_at": now,
            },
        )
        await self._grant(user_id)
        return user_id

    async def _grant(self, user_id: str) -> None:
        await self._roles.ensure(
            "instance",
            INSTANCE_SCOPE_ID,
            PrincipalRef(type="user", id=user_id),
            role="root",
        )
