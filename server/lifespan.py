from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.database.clients import (
    create_database_engine,
    create_session_factory,
)
from packages.database.migrations.runner import upgrade_to_head
from packages.database.queries.organizations import list_organizations

from .services.heartbeat import HeartbeatService, dispatch_all_queued_runs

logger = logging.getLogger(__name__)

SHUTDOWN_TASK_TIMEOUT_SECONDS = 2.0
ENGINE_DISPOSE_TIMEOUT_SECONDS = 2.0


async def _heartbeat_scheduler(
    session_factory: async_sessionmaker[AsyncSession], interval_seconds: float
) -> None:
    try:
        async with session_factory() as session:
            async with session.begin():
                await HeartbeatService(session).recover_orphaned_runs()
        await dispatch_all_queued_runs(session_factory)
    except Exception:
        logger.exception("heartbeat startup recovery failed")
    while True:
        try:
            async with session_factory() as session:
                async with session.begin():
                    heartbeat = HeartbeatService(session)
                    for org in await list_organizations(session):
                        await heartbeat.tick_timers(org.id)
            await dispatch_all_queued_runs(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("heartbeat scheduler tick failed")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    if settings.auto_migrate:
        await upgrade_to_head(settings.database_url)
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    app.state.engine = engine
    app.state.session_factory = session_factory
    scheduler_task = None
    if settings.heartbeat_scheduler_enabled:
        scheduler_task = asyncio.create_task(
            _heartbeat_scheduler(
                session_factory, settings.heartbeat_scheduler_interval_seconds
            )
        )
    try:
        yield
    finally:
        if scheduler_task is not None:
            await _cancel_task(
                scheduler_task,
                "heartbeat scheduler",
                timeout_seconds=SHUTDOWN_TASK_TIMEOUT_SECONDS,
            )
        dispatch_tasks = list(getattr(app.state, "heartbeat_dispatch_tasks", set()))
        if dispatch_tasks:
            await _cancel_tasks(
                dispatch_tasks,
                "heartbeat dispatch tasks",
                timeout_seconds=SHUTDOWN_TASK_TIMEOUT_SECONDS,
            )
        await _dispose_engine(engine, timeout_seconds=ENGINE_DISPOSE_TIMEOUT_SECONDS)


async def _cancel_task(
    task: asyncio.Task[Any], label: str, *, timeout_seconds: float
) -> None:
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=timeout_seconds)
    except asyncio.CancelledError:
        return
    except TimeoutError:
        logger.warning(
            "Timed out waiting for %s to stop after %.1f seconds",
            label,
            timeout_seconds,
        )
    except Exception:
        logger.warning("%s failed during shutdown", label, exc_info=True)


async def _cancel_tasks(
    tasks: list[asyncio.Task[Any]], label: str, *, timeout_seconds: float
) -> None:
    for task in tasks:
        task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        logger.warning(
            "Timed out waiting for %s to stop after %.1f seconds",
            label,
            timeout_seconds,
        )


async def _dispose_engine(engine: AsyncEngine, *, timeout_seconds: float) -> None:
    try:
        await asyncio.wait_for(engine.dispose(), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning(
            "Timed out disposing database engine after %.1f seconds",
            timeout_seconds,
        )
