from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.database.clients import enable_write_transactions
from packages.database.clients.cleanup import (
    close_session_shielded,
    commit_session_shielded,
    rollback_session_shielded,
)
from packages.database.queries.issues import get_issue_by_id
from packages.shared.types.heartbeat import HeartbeatRun


class RunExecutionService:
    """Own the database and Adapter lifecycle for one claimed Run."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        run_id: str,
        agent_id: str,
    ) -> None:
        self._session_factory = session_factory
        self.run_id = run_id
        self.agent_id = agent_id

    async def run(self) -> str | None:
        # Local imports keep the execution service independent from the
        # Heartbeat facade while the facade still hosts lower-level primitives.
        from .heartbeat import (
            HeartbeatService,
            RunExecutionFinalizationError,
            WorkspacePreparationCoordinator,
            _is_sqlite_database_locked_error,
        )

        session = self._session_factory()
        service = HeartbeatService(
            session,
            commit_process_metadata=True,
            session_factory=self._session_factory,
        )
        session_closed = False
        try:
            final = await service.execute_claimed_run(self.run_id)
            reviewer_agent_id = await self._reviewer_to_dispatch(session, final)
            await commit_session_shielded(session)
            return reviewer_agent_id
        except RunExecutionFinalizationError as failure:
            await rollback_session_shielded(session)
            await close_session_shielded(session)
            session_closed = True
            for attempt in range(
                1, WorkspacePreparationCoordinator.MAX_SQLITE_ATTEMPTS + 1
            ):
                clean_session = self._session_factory()
                enable_write_transactions(clean_session)
                try:
                    clean_service = HeartbeatService(
                        clean_session, commit_process_metadata=True
                    )
                    await clean_service.finalize_unhandled_execution_failure(failure)
                    return None
                except Exception as exc:
                    await rollback_session_shielded(clean_session)
                    if (
                        not _is_sqlite_database_locked_error(exc)
                        or attempt
                        >= WorkspacePreparationCoordinator.MAX_SQLITE_ATTEMPTS
                    ):
                        raise
                    await asyncio.sleep(0.05 * (2 ** (attempt - 1)))
                except BaseException:
                    await rollback_session_shielded(clean_session)
                    raise
                finally:
                    await close_session_shielded(clean_session)
            return None
        except BaseException:
            await rollback_session_shielded(session)
            raise
        finally:
            if not session_closed:
                await close_session_shielded(session)

    async def _reviewer_to_dispatch(
        self, session: AsyncSession, final: HeartbeatRun | None
    ) -> str | None:
        if (
            final is None
            or final["status"] != "succeeded"
            or final["invocationSource"] != "assignment"
        ):
            return None
        context = final.get("contextSnapshot")
        issue_id = context.get("issueId") if isinstance(context, dict) else None
        issue = await get_issue_by_id(session, issue_id) if issue_id else None
        if (
            issue is None
            or issue.status != "in_review"
            or not issue.reviewer_agent_id
            or issue.reviewer_agent_id == self.agent_id
        ):
            return None
        return issue.reviewer_agent_id
