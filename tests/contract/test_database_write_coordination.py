from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from packages.database.clients import (
    ConcurrentDatabaseWriteStrategy,
    CoordinatedAsyncSession,
    DatabaseWriteStrategy,
    SQLiteSerializedWriteStrategy,
    async_write_transaction,
    create_database_engine,
    create_session_factory,
)


class CoordinationBase(DeclarativeBase):
    pass


class CoordinationEvent(CoordinationBase):
    __tablename__ = "coordination_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    value: Mapped[str]


def test_database_write_variants_share_one_strategy_boundary() -> None:
    assert isinstance(SQLiteSerializedWriteStrategy(), DatabaseWriteStrategy)
    assert isinstance(ConcurrentDatabaseWriteStrategy(), DatabaseWriteStrategy)


async def _database(tmp_path: Path, name: str = "coordination.db"):
    engine = create_database_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as connection:
        await connection.run_sync(CoordinationBase.metadata.create_all)
    return engine, create_session_factory(engine)


async def test_session_factory_uses_the_database_transaction_layer(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _database(tmp_path)
    try:
        session = session_factory()
        try:
            assert isinstance(session, CoordinatedAsyncSession)
        finally:
            await session.close()
    finally:
        await engine.dispose()


async def test_sqlite_write_transactions_wait_in_one_local_queue(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _database(tmp_path)
    first = session_factory()
    second = session_factory()
    second_started = asyncio.Event()
    try:
        await first.execute(
            text("insert into coordination_events(value) values ('first')")
        )

        async def write_second() -> None:
            second_started.set()
            await second.execute(
                text("insert into coordination_events(value) values ('second')")
            )
            await second.commit()

        second_task = asyncio.create_task(write_second())
        await second_started.wait()
        await asyncio.sleep(0.02)
        assert second_task.done() is False

        await first.commit()
        await asyncio.wait_for(second_task, timeout=1)

        verification = session_factory()
        try:
            values = list(
                await verification.scalars(
                    text("select value from coordination_events order by id")
                )
            )
        finally:
            await verification.close()
        assert values == ["first", "second"]
    finally:
        await first.close()
        await second.close()
        await engine.dispose()


async def test_sqlite_write_intent_reserves_writer_before_the_first_read(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _database(tmp_path, "write-intent.db")
    first = session_factory()
    second = session_factory()
    second_started = asyncio.Event()
    try:
        async with async_write_transaction(first):
            assert (
                await first.scalar(text("select count(*) from coordination_events"))
                == 0
            )

            async def write_second() -> None:
                second_started.set()
                async with async_write_transaction(second):
                    await second.execute(
                        text("insert into coordination_events(value) values ('second')")
                    )

            second_task = asyncio.create_task(write_second())
            await second_started.wait()
            await asyncio.sleep(0.02)
            assert second_task.done() is False

            await first.execute(
                text("insert into coordination_events(value) values ('first')")
            )

        await asyncio.wait_for(second_task, timeout=1)
        verification = session_factory()
        try:
            values = list(
                await verification.scalars(
                    text("select value from coordination_events order by id")
                )
            )
        finally:
            await verification.close()
        assert values == ["first", "second"]
    finally:
        await first.close()
        await second.close()
        await engine.dispose()


async def test_orm_flush_and_commit_use_the_same_sqlite_writer_queue(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _database(tmp_path)
    first = session_factory()
    second = session_factory()
    try:
        first.add(CoordinationEvent(value="first-orm"))
        await first.flush()

        second.add(CoordinationEvent(value="second-orm"))
        second_commit = asyncio.create_task(second.commit())
        await asyncio.sleep(0.02)
        assert second_commit.done() is False

        await first.commit()
        await asyncio.wait_for(second_commit, timeout=1)

        values = set(
            await second.scalars(text("select value from coordination_events"))
        )
        assert values == {"first-orm", "second-orm"}
    finally:
        await first.close()
        await second.close()
        await engine.dispose()


async def test_sqlite_reads_continue_while_another_session_holds_writer(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _database(tmp_path)
    writer = session_factory()
    reader = session_factory()
    try:
        await writer.execute(
            text("insert into coordination_events(value) values ('uncommitted')")
        )

        count = await asyncio.wait_for(
            reader.scalar(text("select count(*) from coordination_events")),
            timeout=0.5,
        )

        assert count == 0
        await writer.rollback()
    finally:
        await writer.close()
        await reader.close()
        await engine.dispose()


async def test_sqlite_rollback_releases_the_next_writer(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _database(tmp_path)
    first = session_factory()
    second = session_factory()
    try:
        await first.execute(
            text("insert into coordination_events(value) values ('rolled-back')")
        )
        second_task = asyncio.create_task(
            second.execute(
                text("insert into coordination_events(value) values ('kept')")
            )
        )
        await asyncio.sleep(0.02)
        assert second_task.done() is False

        await first.rollback()
        await asyncio.wait_for(second_task, timeout=1)
        await second.commit()

        assert (
            await second.scalar(text("select count(*) from coordination_events")) == 1
        )
    finally:
        await first.close()
        await second.close()
        await engine.dispose()


async def test_cancelled_sqlite_waiter_does_not_keep_the_queue_locked(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _database(tmp_path)
    first = session_factory()
    cancelled = session_factory()
    last = session_factory()
    try:
        await first.execute(
            text("insert into coordination_events(value) values ('first')")
        )
        waiting_task = asyncio.create_task(
            cancelled.execute(
                text("insert into coordination_events(value) values ('cancelled')")
            )
        )
        await asyncio.sleep(0.02)
        waiting_task.cancel()
        try:
            await waiting_task
        except asyncio.CancelledError:
            pass

        await first.commit()
        await last.execute(
            text("insert into coordination_events(value) values ('last')")
        )
        await last.commit()

        values = list(
            await last.scalars(
                text("select value from coordination_events order by id")
            )
        )
        assert values == ["first", "last"]
    finally:
        await first.close()
        await cancelled.close()
        await last.close()
        await engine.dispose()


async def test_four_sqlite_workers_commit_through_the_same_writer_queue(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _database(tmp_path)

    async def write(value: str) -> None:
        session = session_factory()
        try:
            await session.execute(
                text("insert into coordination_events(value) values (:value)"),
                {"value": value},
            )
            await asyncio.sleep(0.01)
            await session.commit()
        finally:
            await session.close()

    try:
        await asyncio.gather(*(write(f"worker-{index}") for index in range(4)))
        verification = session_factory()
        try:
            values = set(
                await verification.scalars(
                    text("select value from coordination_events")
                )
            )
        finally:
            await verification.close()
        assert values == {"worker-0", "worker-1", "worker-2", "worker-3"}
    finally:
        await engine.dispose()


@pytest.mark.parametrize("dialect_name", ["postgresql", "mysql"])
async def test_server_databases_bypass_the_sqlite_single_writer_strategy(
    monkeypatch: pytest.MonkeyPatch,
    dialect_name: str,
) -> None:
    session = CoordinatedAsyncSession()
    server_bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
    monkeypatch.setattr(session, "get_bind", lambda: server_bind)
    try:
        await session._acquire_database_write_permit()
        assert session._database_write_permit is None
    finally:
        await session.close()
