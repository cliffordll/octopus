from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging

from anyio import CancelScope

logger = logging.getLogger(__name__)

REQUEST_DB_CLEANUP_TIMEOUT_SECONDS = 2.0


async def run_shielded_cleanup(
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
                observe_background_cleanup(action, cleanup_task)
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
            observe_background_cleanup(action, cleanup_task)
            logger.warning(
                "Database cleanup is still running while trying to %s after %.1f seconds",
                action,
                timeout_seconds,
            )
            return exc
        except BaseException as exc:
            logger.warning("Failed to %s", action, exc_info=True)
            return exc


def observe_background_cleanup(action: str, cleanup_task: asyncio.Future[None]) -> None:
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
