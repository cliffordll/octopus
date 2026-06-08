from __future__ import annotations

from collections.abc import AsyncIterator
import logging

from anyio import CancelScope
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSessionTransaction
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    session = session_factory()
    transaction = await session.begin()
    try:
        yield session
    except BaseException:
        await _rollback_after_error(session, transaction)
        raise
    else:
        with CancelScope(shield=True):
            if transaction.is_active:
                await transaction.commit()
    finally:
        await _close_session(session)


async def _rollback_after_error(
    session: AsyncSession, transaction: AsyncSessionTransaction
) -> None:
    with CancelScope(shield=True):
        if not transaction.is_active:
            return
        try:
            await transaction.rollback()
        except BaseException:
            logger.warning(
                "Failed to roll back request database transaction; invalidating session",
                exc_info=True,
            )
            await _invalidate_session(session)


async def _close_session(session: AsyncSession) -> None:
    with CancelScope(shield=True):
        try:
            await session.close()
        except BaseException:
            logger.warning(
                "Failed to close request database session cleanly; invalidating session",
                exc_info=True,
            )
            await _invalidate_session(session)


async def _invalidate_session(session: AsyncSession) -> None:
    try:
        await session.invalidate()
    except BaseException:
        logger.warning("Failed to invalidate request database session", exc_info=True)
