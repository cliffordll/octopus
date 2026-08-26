from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.database.clients import async_transaction, async_write_transaction
from packages.database.clients.cleanup import close_session_shielded
from packages.database.queries.heartbeat import list_queued_agent_ids

from .run_execution import RunExecutionService


class RunDispatchService:
    """Claims queued Runs and assigns each one to a Run execution service."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def dispatch_agent(self, agent_id: str) -> None:
        from .heartbeat import HeartbeatService

        session = self._session_factory()
        try:
            async with async_write_transaction(session):
                run_ids = await HeartbeatService(session).claim_queued_for_dispatch(
                    agent_id
                )
        finally:
            await close_session_shielded(session)
        if not run_ids:
            return

        next_agent_ids = {
            reviewer_agent_id
            for reviewer_agent_id in await asyncio.gather(
                *(
                    RunExecutionService(
                        self._session_factory,
                        run_id=run_id,
                        agent_id=agent_id,
                    ).run()
                    for run_id in run_ids
                )
            )
            if reviewer_agent_id is not None
        }
        next_agent_ids.add(agent_id)
        queued_session = self._session_factory()
        try:
            async with async_transaction(queued_session):
                next_agent_ids.update(await list_queued_agent_ids(queued_session))
        finally:
            await close_session_shielded(queued_session)
        await asyncio.gather(
            *(self.dispatch_agent(next_agent_id) for next_agent_id in next_agent_ids)
        )

    async def dispatch_all(self) -> None:
        from .heartbeat import HeartbeatService

        session = self._session_factory()
        try:
            async with async_write_transaction(session):
                heartbeat = HeartbeatService(session)
                scheduled_agent_ids = (
                    await heartbeat.materialize_due_scheduled_wakeups()
                )
                agent_ids = scheduled_agent_ids | await list_queued_agent_ids(session)
        finally:
            await close_session_shielded(session)
        await asyncio.gather(*(self.dispatch_agent(agent_id) for agent_id in agent_ids))
