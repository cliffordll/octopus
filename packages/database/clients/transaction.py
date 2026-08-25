from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


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
