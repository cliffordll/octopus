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


def _current_task_is_cancelling() -> bool:
    current_task = asyncio.current_task()
    return current_task is not None and current_task.cancelling() > 0


async def _heartbeat_scheduler(
    session_factory: async_sessionmaker[AsyncSession],
    interval_seconds: float,
    stop_event: asyncio.Event | None = None,
) -> None:
    try:
        async with session_factory() as session:
            async with session.begin():
                await HeartbeatService(session).recover_orphaned_runs()
        await dispatch_all_queued_runs(session_factory)
    except Exception:
        logger.exception("heartbeat startup recovery failed")
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            async with session_factory() as session:
                async with session.begin():
                    heartbeat = HeartbeatService(session)
                    await heartbeat.recover_orphaned_runs(require_process_loss=True)
                    for org in await list_organizations(session):
                        await heartbeat.tick_timers(org.id)
            await dispatch_all_queued_runs(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("heartbeat scheduler tick failed")
        if stop_event is None:
            await asyncio.sleep(interval_seconds)
        else:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                return
            except TimeoutError:
                continue


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
    scheduler_stop_event = None
    if settings.heartbeat_scheduler_enabled:
        scheduler_stop_event = asyncio.Event()
        scheduler_task = asyncio.create_task(
            _heartbeat_scheduler(
                session_factory,
                settings.heartbeat_scheduler_interval_seconds,
                scheduler_stop_event,
            )
        )
    app.state.heartbeat_scheduler_task = scheduler_task
    app.state.heartbeat_scheduler_stop_event = scheduler_stop_event
    try:
        yield
    finally:
        if scheduler_task is not None:
            await _stop_task_cooperatively(
                scheduler_task,
                "heartbeat scheduler",
                stop_event=scheduler_stop_event,
                timeout_seconds=SHUTDOWN_TASK_TIMEOUT_SECONDS,
            )
        app.state.heartbeat_scheduler_task = None
        app.state.heartbeat_scheduler_stop_event = None
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
        if _current_task_is_cancelling():
            raise
        return
    except TimeoutError:
        logger.warning(
            "Timed out waiting for %s to stop after %.1f seconds",
            label,
            timeout_seconds,
        )
    except Exception:
        logger.warning("%s failed during shutdown", label, exc_info=True)


async def _stop_task_cooperatively(
    task: asyncio.Task[Any],
    label: str,
    *,
    stop_event: asyncio.Event | None,
    timeout_seconds: float,
) -> None:
    if stop_event is not None:
        stop_event.set()
    try:
        done, _pending = await asyncio.wait({task}, timeout=timeout_seconds)
        if task in done:
            await task
            return
        logger.warning(
            "Timed out waiting for %s to stop cooperatively after %.1f seconds",
            label,
            timeout_seconds,
        )
    except asyncio.CancelledError:
        if _current_task_is_cancelling():
            raise
        return
    except Exception:
        logger.warning("%s failed during cooperative shutdown", label, exc_info=True)
        return
    await _cancel_task(task, label, timeout_seconds=timeout_seconds)


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
