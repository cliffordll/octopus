from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Account, Session, User


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_password_account(session: AsyncSession, email: str) -> Account | None:
    result = await session.execute(
        select(Account).where(
            Account.provider_id == "credential", Account.account_id == email
        )
    )
    return result.scalar_one_or_none()


async def create_account(session: AsyncSession, fields: Mapping[str, Any]) -> Account:
    row = Account(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def create_session(session: AsyncSession, fields: Mapping[str, Any]) -> Session:
    row = Session(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def get_session_with_user(
    session: AsyncSession, token: str
) -> tuple[Session, User] | None:
    result = await session.execute(
        select(Session, User)
        .join(User, Session.user_id == User.id)
        .where(Session.token == token)
    )
    row = result.one_or_none()
    return (row[0], row[1]) if row is not None else None


async def touch_session(
    session: AsyncSession, session_id: str, updated_at: datetime
) -> None:
    await session.execute(
        update(Session).where(Session.id == session_id).values(updated_at=updated_at)
    )


async def delete_session(session: AsyncSession, token: str) -> None:
    await session.execute(delete(Session).where(Session.token == token))


async def delete_user_sessions(session: AsyncSession, user_id: str) -> None:
    await session.execute(delete(Session).where(Session.user_id == user_id))
