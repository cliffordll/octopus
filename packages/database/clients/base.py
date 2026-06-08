from __future__ import annotations

from pathlib import Path
from types import MethodType
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
    elif backend == "mysql":
        engine_kwargs.update(
            {
                "pool_pre_ping": True,
                "pool_recycle": 1800,
                "connect_args": {"charset": "utf8mb4"},
            }
        )

    engine = create_async_engine(url, **engine_kwargs)
    if backend == "sqlite":
        _configure_sqlite_engine(engine)
    elif parsed_url.drivername == "mysql+asyncmy":
        _configure_asyncmy_terminate(engine)
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


def _configure_asyncmy_terminate(engine: AsyncEngine) -> None:
    def _force_terminate(_: object, dbapi_connection: Any) -> None:
        force_close = getattr(dbapi_connection, "_terminate_force_close", None)
        if callable(force_close):
            force_close()
            return

        raw_connection = getattr(dbapi_connection, "_connection", None)
        close = getattr(raw_connection, "close", None)
        if callable(close):
            close()
            return

        terminate = getattr(dbapi_connection, "terminate", None)
        if callable(terminate):
            terminate()

    engine.sync_engine.dialect.do_terminate = MethodType(  # type: ignore[method-assign]
        _force_terminate,
        engine.sync_engine.dialect,
    )
