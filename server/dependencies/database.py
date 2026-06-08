from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import logging

from anyio import CancelScope
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSessionTransaction
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

REQUEST_DB_CLEANUP_TIMEOUT_SECONDS = 2.0


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
    if error is not None:
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
    if error is not None:
        await _invalidate_session(session)


async def _close_session(session: AsyncSession) -> None:
    error = await _run_shielded_cleanup(
        "close request database session",
        session.close,
        timeout_seconds=REQUEST_DB_CLEANUP_TIMEOUT_SECONDS,
    )
    if error is not None:
        await _invalidate_session(session)


async def _run_shielded_cleanup(
    action: str,
    operation: Callable[[], Awaitable[None]],
    *,
    timeout_seconds: float,
) -> BaseException | None:
    with CancelScope(shield=True):
        try:
            await asyncio.wait_for(operation(), timeout=timeout_seconds)
            return None
        except TimeoutError as exc:
            logger.warning(
                "Timed out while trying to %s after %.1f seconds",
                action,
                timeout_seconds,
            )
            return exc
        except BaseException as exc:
            logger.warning(
                "Failed to %s",
                action,
                exc_info=True,
            )
            return exc


async def _invalidate_session(session: AsyncSession) -> None:
    try:
        await session.invalidate()
    except BaseException:
        logger.warning("Failed to invalidate request database session", exc_info=True)
