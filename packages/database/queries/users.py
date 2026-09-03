from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import User


async def get_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def ensure_user(session: AsyncSession, fields: Mapping[str, Any]) -> User:
    values = dict(fields)
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        await session.execute(
            sqlite_insert(User)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[User.id])
        )
    elif dialect == "postgresql":
        await session.execute(
            postgresql_insert(User)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[User.id])
        )
    else:
        existing = await get_user_by_id(session, str(values["id"]))
        if existing is None:
            session.add(User(**values))
            await session.flush()

    row = await get_user_by_id(session, str(values["id"]))
    if row is None:
        raise RuntimeError("Failed to ensure user")
    return row
