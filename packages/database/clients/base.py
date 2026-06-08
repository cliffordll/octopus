from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_database_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    parsed_url = make_url(url)
    backend = parsed_url.get_backend_name()
    engine_kwargs: dict[str, Any] = {"echo": echo, "future": True}

    if backend == "sqlite":
        _ensure_sqlite_parent_directory(parsed_url.database)
    elif backend == "postgresql":
        engine_kwargs["pool_pre_ping"] = True

    engine = create_async_engine(url, **engine_kwargs)
    if backend == "sqlite":
        _configure_sqlite_engine(engine)
    return engine


def _ensure_sqlite_parent_directory(database: str | None) -> None:
    if not database or database == ":memory:":
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _configure_sqlite_engine(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, _: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=TRUNCATE")
        finally:
            cursor.close()
