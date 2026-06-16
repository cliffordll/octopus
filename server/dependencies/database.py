from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import logging

from anyio import CancelScope
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSessionTransaction

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
        cleanup_coro = operation()
        cleanup_task = asyncio.ensure_future(cleanup_coro)
        try:
            await asyncio.wait_for(
                asyncio.shield(cleanup_task),
                timeout=timeout_seconds,
            )
            return None
        except asyncio.CancelledError:
            try:
                await asyncio.wait_for(
                    asyncio.shield(cleanup_task),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                _observe_background_cleanup(action, cleanup_task)
                logger.warning(
                    "Database cleanup is still running while trying to %s after cancellation",
                    action,
                )
            except BaseException:
                logger.warning(
                    "Failed to %s after cancellation",
                    action,
                    exc_info=True,
                )
            raise
        except TimeoutError as exc:
            _observe_background_cleanup(action, cleanup_task)
            logger.warning(
                "Database cleanup is still running while trying to %s after %.1f seconds",
                action,
                timeout_seconds,
            )
            return exc
        except BaseException as exc:
            logger.warning("Failed to %s", action, exc_info=True)
            return exc


def _observe_background_cleanup(
    action: str, cleanup_task: asyncio.Future[None]
) -> None:
    def _consume_result(task: asyncio.Future[None]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            logger.warning("Background database cleanup was cancelled while %s", action)
        except BaseException:
            logger.warning(
                "Background database cleanup failed while trying to %s",
                action,
                exc_info=True,
            )

    cleanup_task.add_done_callback(_consume_result)


async def _invalidate_session(session: AsyncSession) -> None:
    try:
        await session.invalidate()
    except BaseException:
        logger.warning("Failed to invalidate request database session", exc_info=True)
