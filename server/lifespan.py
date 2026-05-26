from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from packages.database.clients import (
    create_database_engine,
    create_session_factory,
)
from packages.database.migrations.runner import upgrade_to_head


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    if settings.auto_migrate:
        await upgrade_to_head(settings.database_url)
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    app.state.engine = engine
    app.state.session_factory = session_factory
    try:
        yield
    finally:
        await engine.dispose()
