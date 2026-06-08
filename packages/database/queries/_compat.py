from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

T = TypeVar("T")


def supports_update_returning(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bool(getattr(bind.dialect, "update_returning", False))


def supports_delete_returning(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bool(getattr(bind.dialect, "delete_returning", False))


async def update_returning_one(
    session: AsyncSession,
    model: type[T],
    whereclause: ColumnElement[bool],
    values: Mapping[str, Any],
) -> T | None:
    if supports_update_returning(session):
        result = await session.execute(
            update(model).where(whereclause).values(**dict(values)).returning(model)
        )
        return result.scalar_one_or_none()

    result = await session.execute(select(model).where(whereclause))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    await session.execute(update(model).where(whereclause).values(**dict(values)))
    await session.refresh(row)
    return row


async def delete_returning_one(
    session: AsyncSession,
    model: type[T],
    whereclause: ColumnElement[bool],
) -> T | None:
    if supports_delete_returning(session):
        result = await session.execute(
            delete(model).where(whereclause).returning(model)
        )
        return result.scalar_one_or_none()

    result = await session.execute(select(model).where(whereclause))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    await session.execute(
        delete(model).where(whereclause).execution_options(synchronize_session=False)
    )
    return row


async def delete_returning_count(
    session: AsyncSession,
    model: type[T],
    whereclause: ColumnElement[bool],
) -> int:
    if supports_delete_returning(session):
        result = await session.execute(
            delete(model).where(whereclause).returning(model)
        )
        return len(result.scalars().all())

    result = await session.execute(select(model).where(whereclause))
    rows = result.scalars().all()
    if not rows:
        return 0
    await session.execute(
        delete(model).where(whereclause).execution_options(synchronize_session=False)
    )
    return len(rows)
