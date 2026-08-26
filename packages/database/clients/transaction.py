from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from .session import CoordinatedAsyncSession


@asynccontextmanager
async def async_transaction(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await session.begin()
    try:
        yield session
    except BaseException:
        await session.rollback()
        raise
    else:
        await session.commit()


def enable_write_transactions(session: AsyncSession) -> None:
    """Configure a long-lived session whose transaction segments all write."""

    if isinstance(session, CoordinatedAsyncSession):
        session.enable_write_transactions()


async def begin_write_transaction(session: AsyncSession) -> None:
    """Begin one mutation transaction before any route or service reads."""

    if isinstance(session, CoordinatedAsyncSession):
        await session.begin_write()
    else:
        await session.begin()


@asynccontextmanager
async def async_write_transaction(
    session: AsyncSession,
) -> AsyncIterator[AsyncSession]:
    """Open a short mutation transaction with dialect-aware write admission."""

    coordinated = session if isinstance(session, CoordinatedAsyncSession) else None
    await begin_write_transaction(session)
    try:
        yield session
    except BaseException:
        await session.rollback()
        raise
    else:
        await session.commit()
    finally:
        if coordinated is not None:
            coordinated.disable_write_transactions()
