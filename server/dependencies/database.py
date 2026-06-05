from __future__ import annotations

from collections.abc import AsyncIterator

from anyio import CancelScope
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    transaction = await session.begin()
    try:
        yield session
    except BaseException:
        with CancelScope(shield=True):
            if transaction.is_active:
                await transaction.rollback()
        raise
    else:
        with CancelScope(shield=True):
            if transaction.is_active:
                await transaction.commit()
    finally:
        with CancelScope(shield=True):
            await session.close()
