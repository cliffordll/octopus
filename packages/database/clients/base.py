from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


def create_database_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    parsed_url = make_url(url)
    engine_kwargs: dict[str, Any] = {"echo": echo, "future": True}
    if parsed_url.get_backend_name() == "sqlite" and parsed_url.database not in (
        None,
        "",
        ":memory:",
    ):
        engine_kwargs["poolclass"] = NullPool
    engine = create_async_engine(url, **engine_kwargs)
    if engine.url.get_backend_name() == "sqlite":
        _configure_sqlite_engine(engine)
    return engine


def _configure_sqlite_engine(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, _: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=TRUNCATE")
        finally:
            cursor.close()
