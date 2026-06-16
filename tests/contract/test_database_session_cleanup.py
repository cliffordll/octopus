from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
import inspect
from types import SimpleNamespace
from typing import cast

import pytest

from server.dependencies import database as database_dependency
from server.dependencies.database import get_session
from server.lifespan import _dispose_engine
from server.routes import agents as agent_routes
from server.routes import chats as chat_routes


class BrokenTransaction:
    is_active = True

    def __init__(self) -> None:
        self.rollback_called = False

    async def rollback(self) -> None:
        self.rollback_called = True
        raise RuntimeError("rollback connection is already broken")

    async def commit(self) -> None:
        raise AssertionError("commit should not run on exception")


class BrokenSession:
    def __init__(self) -> None:
        self.transaction = BrokenTransaction()
        self.close_called = False
        self.invalidate_called = False

    async def begin(self) -> BrokenTransaction:
        return self.transaction

    async def close(self) -> None:
        self.close_called = True
        raise RuntimeError("close connection is already broken")

    async def invalidate(self) -> None:
        self.invalidate_called = True


class SlowCloseSession:
    def __init__(self) -> None:
        self.invalidate_called = False
        self.close_finished = False

    async def close(self) -> None:
        await asyncio.sleep(0.05)
        self.close_finished = True

    async def invalidate(self) -> None:
        self.invalidate_called = True


class SlowDisposeEngine:
    def __init__(self) -> None:
        self.dispose_started = False

    async def dispose(self) -> None:
        self.dispose_started = True
        await asyncio.sleep(10)


async def test_get_session_preserves_original_exception_when_cleanup_fails() -> None:
    session = BrokenSession()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    request.app.state.session_factory = lambda: session
    dependency = cast(
        AsyncGenerator[object, object],
        get_session(request),  # type: ignore[arg-type]
    )

    yielded = await anext(dependency)
    assert yielded is session

    with pytest.raises(ValueError, match="route failed"):
        await dependency.athrow(ValueError("route failed"))

    assert session.transaction.rollback_called
    assert session.invalidate_called
    assert session.close_called


async def test_close_session_timeout_keeps_background_close_without_invalidating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(database_dependency, "REQUEST_DB_CLEANUP_TIMEOUT_SECONDS", 0.01)
    session = SlowCloseSession()

    await database_dependency._close_session(session)  # type: ignore[arg-type]

    assert session.invalidate_called is False
    await asyncio.sleep(0.06)
    assert session.close_finished


async def test_shielded_cleanup_finishes_before_propagating_task_cancellation() -> None:
    cleanup_started = asyncio.Event()
    cleanup_finished = asyncio.Event()

    async def cleanup() -> None:
        cleanup_started.set()
        await asyncio.sleep(0.02)
        cleanup_finished.set()

    task = asyncio.create_task(
        database_dependency._run_shielded_cleanup(
            "test cleanup",
            cleanup,
            timeout_seconds=1.0,
        )
    )
    await cleanup_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleanup_finished.is_set()


async def test_shielded_cleanup_timeout_does_not_cancel_database_reset() -> None:
    cleanup_cancelled = False

    async def cleanup() -> None:
        nonlocal cleanup_cancelled
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            cleanup_cancelled = True
            raise

    error = await database_dependency._run_shielded_cleanup(
        "test cleanup",
        cleanup,
        timeout_seconds=0.01,
    )

    assert isinstance(error, TimeoutError)
    await asyncio.sleep(0.06)
    assert cleanup_cancelled is False


def test_cleanup_timeout_does_not_require_connection_invalidation() -> None:
    assert (
        database_dependency._cleanup_error_requires_invalidate(TimeoutError())
        is False
    )
    assert (
        database_dependency._cleanup_error_requires_invalidate(
            RuntimeError("connection is broken")
        )
        is True
    )


async def test_dispose_engine_times_out() -> None:
    engine = SlowDisposeEngine()

    await _dispose_engine(engine, timeout_seconds=0.01)  # type: ignore[arg-type]

    assert engine.dispose_started


def test_heartbeat_run_stream_uses_shielded_session_cleanup() -> None:
    source = inspect.getsource(agent_routes.stream_heartbeat_run_route)

    assert "heartbeat: HeartbeatService = Depends(get_heartbeat_service)" not in source
    assert "async with session_factory() as session" not in source
    assert source.count("_close_session(session)") >= 2


def test_chat_message_stream_uses_shielded_session_cleanup() -> None:
    source = inspect.getsource(chat_routes.add_chat_message_stream_route)

    assert "async with session_factory() as session" not in source
    assert "_close_session(session)" in source
