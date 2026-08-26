from __future__ import annotations

from datetime import UTC
import hashlib
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.issues import get_issue_by_id
from packages.database.schema import ActivityLog, HeartbeatRun, Issue
from packages.shared.types.heartbeat import HeartbeatRun as HeartbeatRunData
from packages.shared.types.heartbeat import WakeAgentPayload

from .delegation_closeout import DelegationBatch, DelegationBatchStore


class ParentContinuationHost(Protocol):
    last_wakeup_reused: bool

    async def wakeup(
        self,
        agent_id: str,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
        execute_immediately: bool = True,
    ) -> HeartbeatRunData | None: ...


class ParentContinuationCoordinator:
    """Owns settlement detection and exactly-once parent continuation wakeups."""

    def __init__(self, session: AsyncSession, host: ParentContinuationHost) -> None:
        self._session = session
        self._host = host

    async def settlement_cycle_key(
        self,
        parent_id: str,
        *,
        batch: DelegationBatch | None = None,
    ) -> str | None:
        children = (
            list(batch.children)
            if batch is not None
            else (
                (
                    await self._session.execute(
                        select(Issue)
                        .where(
                            Issue.parent_id == parent_id,
                            Issue.hidden_at.is_(None),
                        )
                        .order_by(Issue.id)
                        .execution_options(populate_existing=True)
                    )
                )
                .scalars()
                .all()
            )
        )
        if not children or any(
            child.status not in {"done", "cancelled", "blocked"} for child in children
        ):
            return None
        child_run_ids = {
            run_id
            for child in children
            for run_id in (child.execution_run_id, child.checkout_run_id)
            if run_id
        }
        if child_run_ids:
            active_child_run = (
                await self._session.execute(
                    select(HeartbeatRun.id)
                    .where(
                        HeartbeatRun.id.in_(child_run_ids),
                        HeartbeatRun.status.in_(("queued", "running")),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if active_child_run is not None:
                return None
        parts = [
            f"{child.id}:{await self._issue_settlement_cycle_key(child)}"
            for child in children
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    async def queue_for_settled_child(
        self,
        child_issue_id: str,
        *,
        expected_org_id: str | None = None,
    ) -> str | None:
        child = await get_issue_by_id(self._session, child_issue_id)
        if child is None or (
            expected_org_id is not None and child.org_id != expected_org_id
        ):
            return None
        if child.parent_id is None or child.status not in {
            "done",
            "cancelled",
            "blocked",
        }:
            return None
        parent = (
            await self._session.execute(
                select(Issue).where(Issue.id == child.parent_id).with_for_update()
            )
        ).scalar_one_or_none()
        if (
            parent is None
            or parent.org_id != child.org_id
            or parent.status not in {"backlog", "todo", "in_progress", "blocked"}
        ):
            return None
        batch = await DelegationBatchStore(self._session).for_child(child)
        if batch is None:
            return None
        if parent.status == "blocked":
            return None
        settlement_cycle_key = await self.settlement_cycle_key(parent.id, batch=batch)
        if settlement_cycle_key is None:
            return None
        if not parent.assignee_agent_id:
            return None
        delegation_context = (
            {
                "delegationOriginRunId": batch.origin_run_id,
                "closeoutPolicy": batch.closeout_policy,
            }
            if batch.origin_run_id is not None
            else {}
        )
        continuation = await self._host.wakeup(
            parent.assignee_agent_id,
            {
                "source": "assignment",
                "triggerDetail": "system",
                "reason": "issue_children_settled",
                "idempotencyKey": (
                    f"issue:{parent.id}:children_settled:{settlement_cycle_key}"
                ),
                "payload": {
                    "issueId": parent.id,
                    "mutation": "children_settled",
                    "completedChildIssueId": child.id,
                    **delegation_context,
                },
                "contextSnapshot": {
                    "issueId": parent.id,
                    "source": "issue.children_settled",
                    "wakeSource": "assignment",
                    "wakeReason": "issue_children_settled",
                    "completedChildIssueId": child.id,
                    **delegation_context,
                    "issue": {
                        "id": parent.id,
                        "identifier": parent.identifier,
                        "title": parent.title,
                        "description": parent.description,
                        "status": parent.status,
                        "priority": parent.priority,
                    },
                },
            },
            actor_type="system",
            actor_id="heartbeat_child_coordination",
            execute_immediately=False,
        )
        if continuation is not None and not self._host.last_wakeup_reused:
            await insert_activity_log(
                self._session,
                org_id=parent.org_id,
                actor_type="system",
                actor_id="heartbeat_child_coordination",
                action="issue.children_settled",
                entity_type="issue",
                entity_id=parent.id,
                run_id=None,
                details={
                    "parentIssueId": parent.id,
                    "completedChildIssueId": child.id,
                    "completedChildIdentifier": child.identifier,
                    "completedChildTitle": child.title,
                    "reason": "issue_children_settled",
                    "delegationOriginRunId": batch.origin_run_id,
                    "closeoutPolicy": batch.closeout_policy,
                },
            )
        return parent.assignee_agent_id

    async def _issue_settlement_cycle_key(self, issue: Issue) -> str:
        activities = (
            (
                await self._session.execute(
                    select(ActivityLog)
                    .where(
                        ActivityLog.org_id == issue.org_id,
                        ActivityLog.entity_type == "issue",
                        ActivityLog.entity_id == issue.id,
                        ActivityLog.action.in_(
                            (
                                "issue.created",
                                "issue.updated",
                                "issue.review_decision_recorded",
                            )
                        ),
                    )
                    .order_by(ActivityLog.created_at, ActivityLog.id)
                )
            )
            .scalars()
            .all()
        )
        current_status: str | None = None
        terminal_activity_id: str | None = None
        review_statuses = {
            "approve": "done",
            "request_changes": "in_progress",
            "blocked": "blocked",
        }
        terminal_statuses = {"done", "cancelled", "blocked"}
        for activity in activities:
            details = activity.details if isinstance(activity.details, dict) else {}
            status = details.get("status")
            if activity.action == "issue.review_decision_recorded":
                decision = details.get("decision")
                status = (
                    review_statuses.get(decision) if isinstance(decision, str) else None
                )
            elif (
                not isinstance(status, str)
                and details.get("reopen") is True
                and current_status in {"done", "cancelled"}
            ):
                status = "todo"
            if not isinstance(status, str) or status == current_status:
                continue
            current_status = status
            terminal_activity_id = activity.id if status in terminal_statuses else None
        if current_status == issue.status and terminal_activity_id is not None:
            return f"activity:{terminal_activity_id}"
        terminal_at = (
            issue.completed_at
            if issue.status == "done"
            else issue.cancelled_at
            if issue.status == "cancelled"
            else None
        )
        if terminal_at is not None:
            if terminal_at.tzinfo is None:
                terminal_at = terminal_at.replace(tzinfo=UTC)
            return f"{issue.status}:{terminal_at.isoformat()}"
        return f"{issue.status}:legacy"
