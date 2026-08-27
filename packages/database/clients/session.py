from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from .coordination import DatabaseTransactionCoordinator, DatabaseWritePermit


class CoordinatedAsyncSession(AsyncSession):
    """Serialize SQLite write transactions without serializing reads or adapters.

    SQLite permits concurrent readers but only one writer.  Letting independent
    request, dispatcher, and recovery sessions race for that writer slot makes
    otherwise short API calls wait inside the driver and can surface as HTTP
    timeouts. Write-intent transactions acquire a process-local permit and issue
    ``BEGIN IMMEDIATE`` before their first read, preventing a stale read snapshot
    from later failing while it is upgraded to a SQLite write transaction.

    PostgreSQL/MySQL sessions deliberately bypass this coordinator and continue
    to use database row locks and compare-and-swap claims for concurrency control.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._database_write_permit: DatabaseWritePermit | None = None
        self._write_transaction_mode = False

    def enable_write_transactions(self) -> None:
        """Make each new transaction reserve its writer slot before any read."""

        self._write_transaction_mode = True

    def disable_write_transactions(self) -> None:
        self._write_transaction_mode = False

    async def begin_write(self) -> None:
        """Begin a dialect-aware transaction that is known to mutate data."""

        self.enable_write_transactions()
        await self._ensure_write_transaction_started()

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        await self._coordinate_database_operation(statement)
        return await super().execute(statement, *args, **kwargs)

    async def scalar(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        await self._coordinate_database_operation(statement)
        return await super().scalar(statement, *args, **kwargs)

    async def scalars(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        await self._coordinate_database_operation(statement)
        return await super().scalars(statement, *args, **kwargs)

    async def stream(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        await self._coordinate_database_operation(statement)
        return await super().stream(statement, *args, **kwargs)

    async def stream_scalars(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        await self._coordinate_database_operation(statement)
        return await super().stream_scalars(statement, *args, **kwargs)

    async def run_sync(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        # A synchronous callback can issue arbitrary SQL through the underlying
        # Session, so conservatively treat it as a write-capable operation.
        await self._ensure_write_transaction_started()
        await self._acquire_database_write_permit()
        return await super().run_sync(fn, *args, **kwargs)

    async def get(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        await self._ensure_write_transaction_started()
        await self._acquire_if_pending_orm_writes()
        return await super().get(entity, ident, **kwargs)

    async def get_one(self, entity: Any, ident: Any, **kwargs: Any) -> Any:
        await self._ensure_write_transaction_started()
        await self._acquire_if_pending_orm_writes()
        return await super().get_one(entity, ident, **kwargs)

    async def merge(self, instance: Any, **kwargs: Any) -> Any:
        await self._ensure_write_transaction_started()
        await self._acquire_if_pending_orm_writes()
        return await super().merge(instance, **kwargs)

    async def refresh(self, instance: Any, *args: Any, **kwargs: Any) -> None:
        await self._ensure_write_transaction_started()
        await self._acquire_if_pending_orm_writes()
        await super().refresh(instance, *args, **kwargs)

    async def flush(self, objects: Any = None) -> None:
        await self._ensure_write_transaction_started()
        if objects is not None or self._has_pending_orm_writes():
            await self._acquire_database_write_permit()
        await super().flush(objects)

    async def commit(self) -> None:
        await self._acquire_if_pending_orm_writes()
        try:
            await super().commit()
        except BaseException:
            try:
                await super().rollback()
            finally:
                self._release_database_write_permit()
            raise
        else:
            self._release_database_write_permit()

    async def rollback(self) -> None:
        try:
            await super().rollback()
        finally:
            self._release_database_write_permit()

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            self._release_database_write_permit()

    async def invalidate(self) -> None:
        try:
            await super().invalidate()
        finally:
            self._release_database_write_permit()

    async def reset(self) -> None:
        try:
            await super().reset()
        finally:
            self._release_database_write_permit()

    async def _coordinate_database_operation(self, statement: Any) -> None:
        await self._ensure_write_transaction_started()
        if self._statement_is_write(statement) or self._has_pending_orm_writes():
            await self._acquire_database_write_permit()

    async def _ensure_write_transaction_started(self) -> None:
        if not self._write_transaction_mode or self.in_transaction():
            return
        bind = self.get_bind()
        await self._acquire_database_write_permit()
        try:
            if bind.dialect.name == "sqlite":
                await super().execute(text("BEGIN IMMEDIATE"))
            else:
                await super().begin()
        except BaseException:
            self._release_database_write_permit()
            raise

    async def _acquire_if_pending_orm_writes(self) -> None:
        if self._has_pending_orm_writes():
            await self._acquire_database_write_permit()

    def _has_pending_orm_writes(self) -> bool:
        return bool(self.new or self.dirty or self.deleted)

    @staticmethod
    def _statement_is_write(statement: Any) -> bool:
        if bool(getattr(statement, "is_dml", False)):
            return True
        text = getattr(statement, "text", None)
        if not isinstance(text, str):
            return False
        tokens = text.lstrip().split(None, 1)
        first_token = tokens[0].lower() if tokens else ""
        return first_token in {
            "alter",
            "attach",
            "create",
            "delete",
            "detach",
            "drop",
            "insert",
            "pragma",
            "reindex",
            "replace",
            "update",
            "vacuum",
        }

    async def _acquire_database_write_permit(self) -> None:
        if self._database_write_permit is not None:
            return
        self._database_write_permit = (
            await DatabaseTransactionCoordinator.acquire_write_permit(self.get_bind())
        )

    def _release_database_write_permit(self) -> None:
        permit = self._database_write_permit
        self._database_write_permit = None
        if permit is not None:
            permit.release()


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        class_=CoordinatedAsyncSession,
        expire_on_commit=False,
    )
