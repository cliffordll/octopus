from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import cast

import pytest

from server.dependencies.database import get_session


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
