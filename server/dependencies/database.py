from __future__ import annotations

from collections.abc import AsyncIterator
import asyncio
import logging

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSessionTransaction

from packages.database.clients.cleanup import (
    REQUEST_DB_CLEANUP_TIMEOUT_SECONDS,
    run_shielded_cleanup as _run_shielded_cleanup,
)

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
        await _commit_after_success(session, transaction)
    finally:
        await _close_session(session)


async def _commit_after_success(
    session: AsyncSession, transaction: AsyncSessionTransaction
) -> None:
    if not transaction.is_active:
        return
    error = await _run_shielded_cleanup(
        "commit request database transaction",
        transaction.commit,
        timeout_seconds=REQUEST_DB_CLEANUP_TIMEOUT_SECONDS,
    )
    if error is None:
        return
    if _cleanup_error_requires_invalidate(error):
        await _invalidate_session(session)
    raise error


async def _rollback_after_error(
    session: AsyncSession, transaction: AsyncSessionTransaction
) -> None:
    if not transaction.is_active:
        return
    error = await _run_shielded_cleanup(
        "roll back request database transaction",
        transaction.rollback,
        timeout_seconds=REQUEST_DB_CLEANUP_TIMEOUT_SECONDS,
    )
    if _cleanup_error_requires_invalidate(error):
        await _invalidate_session(session)


async def _close_session(session: AsyncSession) -> None:
    error = await _run_shielded_cleanup(
        "close request database session",
        session.close,
        timeout_seconds=REQUEST_DB_CLEANUP_TIMEOUT_SECONDS,
    )
    if _cleanup_error_requires_invalidate(error):
        await _invalidate_session(session)


def _cleanup_error_requires_invalidate(error: BaseException | None) -> bool:
    return error is not None and not isinstance(
        error, (TimeoutError, asyncio.CancelledError)
    )


async def _invalidate_session(session: AsyncSession) -> None:
    try:
        await session.invalidate()
    except BaseException:
        logger.warning("Failed to invalidate request database session", exc_info=True)
