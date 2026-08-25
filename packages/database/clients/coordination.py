from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from time import monotonic
from typing import Any, ClassVar
from weakref import WeakKeyDictionary

from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


@dataclass
class DatabaseWritePermit:
    """An idempotently releasable permit for one database write transaction."""

    _lock: asyncio.Lock | None = None

    def release(self) -> None:
        lock = self._lock
        self._lock = None
        if lock is not None and lock.locked():
            lock.release()


class DatabaseTransactionCoordinator:
    """Select the concurrency strategy for a database transaction.

    SQLite engines use one local writer queue per engine. PostgreSQL, MySQL,
    and other server databases retain their native concurrent-write behavior;
    their correctness boundaries remain row locks, constraints, and CAS.
    """

    WRITE_WAIT_WARNING_SECONDS = 1.0
    _sqlite_write_locks: ClassVar[WeakKeyDictionary[Engine, asyncio.Lock]] = (
        WeakKeyDictionary()
    )

    @classmethod
    async def acquire_write_permit(cls, bind: Any) -> DatabaseWritePermit | None:
        if bind.dialect.name != "sqlite":
            return None
        lock = cls._sqlite_write_locks.get(bind)
        if lock is None:
            lock = asyncio.Lock()
            cls._sqlite_write_locks[bind] = lock
        started_at = monotonic()
        await lock.acquire()
        waited_seconds = monotonic() - started_at
        if waited_seconds >= cls.WRITE_WAIT_WARNING_SECONDS:
            logger.warning(
                "SQLite write transaction waited %.3f seconds for the local writer",
                waited_seconds,
            )
        return DatabaseWritePermit(lock)
