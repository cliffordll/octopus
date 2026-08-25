from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.shared.types.heartbeat import HeartbeatRun
from packages.shared.types.issue import IssueDetail

from .heartbeat import HeartbeatService
from .issues import IssueService


class ChildRecoveryUnavailable(ValueError):
    """Raised when retry-before-replacement policy cannot advance."""


@dataclass(frozen=True)
class ChildRunLineage:
    terminal_run: dict[str, Any]
    retry_attempts: int


class ChildRecoveryCoordinator:
    """Own retry-before-replacement decisions for one persistent child Issue."""

    TERMINAL_RETRY_STATUSES = {"failed", "timed_out", "cancelled"}
    MAX_RETRY_ATTEMPTS = 1

    def __init__(
        self,
        issues: IssueService,
        heartbeat: HeartbeatService,
    ) -> None:
        self._issues = issues
        self._heartbeat = heartbeat

    async def retry(
        self,
        child: IssueDetail,
        *,
        actor_type: str,
        actor_id: str,
        run_id: str | None,
    ) -> HeartbeatRun:
        lineage = await self._lineage(child["id"])
        if lineage.retry_attempts >= self.MAX_RETRY_ATTEMPTS:
            raise ChildRecoveryUnavailable(
                "Child retry limit reached; replace the child, accept the "
                "incomplete result, or block the parent."
            )
        await self._issues.update_issue(
            child["id"],
            {"status": "in_progress", "comment": "Retrying blocked child issue."},
            actor_type=actor_type,
            actor_id=actor_id,
            run_id=run_id,
        )
        retried = await self._heartbeat.retry_run(
            str(lineage.terminal_run["runId"]),
            actor_type=actor_type,
            actor_id=actor_id,
            execute_immediately=False,
            recovery_trigger="manual",
        )
        if retried is None:
            raise ChildRecoveryUnavailable("Run not found")
        return retried

    async def require_failed_retry_before_replacement(self, child_id: str) -> None:
        lineage = await self._lineage(child_id)
        if lineage.retry_attempts < self.MAX_RETRY_ATTEMPTS:
            raise ChildRecoveryUnavailable(
                "Retry the existing child once before creating a replacement"
            )

    async def _lineage(self, child_id: str) -> ChildRunLineage:
        runs = await self._heartbeat.list_for_issue(child_id)
        terminal = next(
            (
                run
                for run in runs or []
                if run.get("status") in self.TERMINAL_RETRY_STATUSES
            ),
            None,
        )
        if terminal is None:
            raise ChildRecoveryUnavailable(
                "Child issue has no failed, timed out, or cancelled run"
            )
        runs_by_id = {
            str(run["runId"]): run
            for run in runs or []
            if isinstance(run.get("runId"), str)
        }
        retry_attempts = 0
        cursor = terminal
        seen_run_ids: set[str] = set()
        while isinstance(cursor.get("retryOfRunId"), str):
            retry_attempts += 1
            retry_of = str(cursor["retryOfRunId"])
            if retry_of in seen_run_ids:
                break
            seen_run_ids.add(retry_of)
            previous = runs_by_id.get(retry_of)
            if previous is None:
                break
            cursor = previous
        return ChildRunLineage(terminal_run=terminal, retry_attempts=retry_attempts)
