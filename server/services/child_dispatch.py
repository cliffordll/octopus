from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Awaitable, Callable, Sequence

from packages.shared.types.issue import IssueDetail

from .heartbeat import HeartbeatService
from .issue_assignment_wakeup import queue_issue_assignment_wakeup


@dataclass(frozen=True)
class ChildDispatchResult:
    """Durable child dispatch intents created by one atomic parent operation."""

    agent_ids: tuple[str, ...]


class ChildDispatchCoordinator:
    """Materialize runnable child wakeups without coupling them to the parent Run."""

    def __init__(
        self,
        heartbeat: HeartbeatService,
        *,
        queue_assignment: Callable[..., Awaitable[bool]] = (
            queue_issue_assignment_wakeup
        ),
    ) -> None:
        self._heartbeat = heartbeat
        self._queue_assignment = queue_assignment

    async def materialize(
        self,
        children: Sequence[IssueDetail],
        *,
        created: bool,
        actor_type: str,
        actor_id: str,
        mutation: str = "create_children_batch",
        context_source: str = "issue.children_batch",
    ) -> ChildDispatchResult:
        agent_ids: set[str] = set()
        for child in children:
            if not created and child["status"] not in {"todo", "in_progress"}:
                continue
            if child.get("assigneeUserId"):
                continue
            queued = await self._queue_assignment(
                self._heartbeat,
                child,
                reason="issue_assigned",
                mutation=mutation,
                context_source=context_source,
                actor_type="agent" if actor_type == "agent" else "user",
                actor_id=actor_id,
                idempotency_key=(
                    f"issue:{child['id']}:initial-assignment:"
                    f"{child.get('assigneeAgentId') or 'unassigned'}"
                ),
                suppress_errors=False,
            )
            assignee_agent_id = child.get("assigneeAgentId")
            if assignee_agent_id and queued:
                agent_ids.add(assignee_agent_id)
        return ChildDispatchResult(tuple(sorted(agent_ids)))
