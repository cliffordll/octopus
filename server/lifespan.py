from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from packages.database.clients import (
    create_database_engine,
    create_session_factory,
)
from packages.database.schema import Base


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    # Dev convenience: auto-create schema on SQLite so a freshly cloned repo
    # can start the server against an empty file without an external migration
    # step. PostgreSQL deployments are expected to manage schema via a real
    # migration tool (alembic landing in a later step), so this no-ops there.
    if "sqlite" in settings.database_url:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    app.state.engine = engine
    app.state.session_factory = session_factory
    try:
        yield
    finally:
        await engine.dispose()
