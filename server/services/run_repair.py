from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.heartbeat import list_runs
from packages.database.queries.issues import get_issue_by_id
from packages.database.schema import HeartbeatRun, Issue

from .heartbeat import (
    RUN_RECOVERY_GRACE_SECONDS,
    HeartbeatService,
)


class IssueRunRepairService:
    """Inspect and narrowly recover damaged Runs belonging to one Issue tree."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def inspect(self, issue_id: str) -> dict[str, Any]:
        root = await get_issue_by_id(self._session, issue_id)
        if root is None:
            raise ValueError("Issue not found")
        issues = await self._issue_tree(root)
        issue_refs = {
            ref
            for issue in issues
            for ref in (issue.id, issue.identifier)
            if isinstance(ref, str) and ref
        }
        now = datetime.now(UTC)
        matching_runs = [
            run
            for run in await list_runs(self._session, root.org_id)
            if _run_issue_ref(run) in issue_refs
        ]
        running = [
            self._running_evidence(run, now)
            for run in matching_runs
            if run.status == "running"
        ]
        return {
            "mode": "dry-run",
            "rootIssue": _issue_summary(root),
            "issues": [_issue_summary(issue) for issue in issues],
            "runningRuns": running,
            "candidateRunIds": [row["id"] for row in running if row["candidate"]],
            "matchingRunCount": len(matching_runs),
        }

    async def repair(self, issue_id: str) -> dict[str, Any]:
        before = await self.inspect(issue_id)
        candidate_ids = set(before["candidateRunIds"])
        heartbeat = HeartbeatService(self._session)
        recovered = []
        if candidate_ids:
            recovered = await heartbeat.recovery.recover(
                require_process_loss=True,
                run_ids=candidate_ids,
            )
        restored_issue_ids: list[str] = []
        root = await get_issue_by_id(self._session, issue_id)
        assert root is not None
        issues = await self._issue_tree(root)
        issue_refs = {
            ref
            for issue in issues
            for ref in (issue.id, issue.identifier)
            if isinstance(ref, str) and ref
        }
        for run in await list_runs(self._session, root.org_id):
            issue_ref = _run_issue_ref(run)
            if issue_ref not in issue_refs:
                continue
            if await heartbeat.finalizer.restore_system_blocked_issue_after_recovery(
                run
            ):
                restored_issue = await get_issue_by_id(self._session, issue_ref)
                if restored_issue is not None:
                    restored_issue_ids.append(restored_issue.id)
        after = await self.inspect(issue_id)
        return {
            "mode": "apply",
            "rootIssue": before["rootIssue"],
            "candidateRunIds": sorted(candidate_ids),
            "recoveryRuns": recovered,
            "restoredIssueIds": sorted(set(restored_issue_ids)),
            "before": before,
            "after": after,
        }

    async def _issue_tree(self, root: Issue) -> list[Issue]:
        issues = [root]
        frontier = [root.id]
        seen = {root.id}
        while frontier:
            rows = (
                (
                    await self._session.execute(
                        select(Issue).where(
                            Issue.org_id == root.org_id,
                            Issue.parent_id.in_(frontier),
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                break
            new_rows = [row for row in rows if row.id not in seen]
            if not new_rows:
                break
            issues.extend(new_rows)
            frontier = [row.id for row in new_rows]
            seen.update(frontier)
        return issues

    def _running_evidence(self, run: HeartbeatRun, now: datetime) -> dict[str, Any]:
        lease_expires_at = _aware(run.execution_lease_expires_at)
        baseline = _aware(run.started_at or run.updated_at or run.created_at)
        lease_state = (
            "missing"
            if lease_expires_at is None
            else "valid"
            if lease_expires_at > now
            else "expired"
        )
        candidate = lease_state == "expired" or (
            lease_state == "missing"
            and baseline is not None
            and baseline + timedelta(seconds=RUN_RECOVERY_GRACE_SECONDS) <= now
        )
        return {
            "id": run.id,
            "agentId": run.agent_id,
            "invocationSource": run.invocation_source,
            "issueRef": _run_issue_ref(run),
            "processPid": run.process_pid,
            "hasExecutionOwner": run.execution_owner_token is not None,
            "executionLeaseExpiresAt": (
                lease_expires_at.isoformat() if lease_expires_at else None
            ),
            "leaseState": lease_state,
            "candidate": candidate,
        }


def _run_issue_ref(run: HeartbeatRun) -> str | None:
    context = run.context_snapshot if isinstance(run.context_snapshot, dict) else {}
    value = context.get("issueId") or context.get("primaryIssueId")
    return value if isinstance(value, str) and value else None


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _issue_summary(issue: Issue) -> dict[str, Any]:
    return {
        "id": issue.id,
        "identifier": issue.identifier,
        "parentId": issue.parent_id,
        "title": issue.title,
        "status": issue.status,
        "hidden": issue.hidden_at is not None,
    }
