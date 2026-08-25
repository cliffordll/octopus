from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
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


class DatabaseWriteStrategy(ABC):
    """Extension point for dialect-specific write admission."""

    @abstractmethod
    async def acquire(self, bind: Any) -> DatabaseWritePermit | None:
        """Acquire permission to start a write transaction."""


class ConcurrentDatabaseWriteStrategy(DatabaseWriteStrategy):
    """Let server databases use their native concurrent-write semantics."""

    async def acquire(self, bind: Any) -> DatabaseWritePermit | None:
        return None


class SQLiteSerializedWriteStrategy(DatabaseWriteStrategy):
    """Serialize only SQLite write transactions per local engine."""

    WRITE_WAIT_WARNING_SECONDS = 1.0
    _write_locks: ClassVar[WeakKeyDictionary[Engine, asyncio.Lock]] = (
        WeakKeyDictionary()
    )

    async def acquire(self, bind: Any) -> DatabaseWritePermit | None:
        lock = self._write_locks.get(bind)
        if lock is None:
            lock = asyncio.Lock()
            self._write_locks[bind] = lock
        started_at = monotonic()
        await lock.acquire()
        waited_seconds = monotonic() - started_at
        if waited_seconds >= self.WRITE_WAIT_WARNING_SECONDS:
            logger.warning(
                "SQLite write transaction waited %.3f seconds for the local writer",
                waited_seconds,
            )
        return DatabaseWritePermit(lock)


class DatabaseTransactionCoordinator:
    """Select a database write strategy and expose one stable session API.

    SQLite engines use one local writer queue per engine. PostgreSQL, MySQL,
    and other server databases retain their native concurrent-write behavior;
    their correctness boundaries remain row locks, constraints, and CAS.
    """

    _sqlite_strategy = SQLiteSerializedWriteStrategy()
    _concurrent_strategy = ConcurrentDatabaseWriteStrategy()

    @classmethod
    async def acquire_write_permit(cls, bind: Any) -> DatabaseWritePermit | None:
        strategy = (
            cls._sqlite_strategy
            if bind.dialect.name == "sqlite"
            else cls._concurrent_strategy
        )
        return await strategy.acquire(bind)
