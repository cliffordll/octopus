from __future__ import annotations

from dataclasses import dataclass

from packages.shared.types.issue import IssueDetail

from .heartbeat import HeartbeatService


class ParentChildControlDenied(ValueError):
    """Raised when an Agent tries to control children outside its parent Run."""


@dataclass(frozen=True)
class ParentChildControlContext:
    parent: IssueDetail
    child: IssueDetail | None = None


class ParentChildControlAuthorizer:
    """Enforce the parent Issue/Run authority boundary for child mutations."""

    def __init__(self, heartbeat: HeartbeatService) -> None:
        self._heartbeat = heartbeat

    async def authorize(
        self,
        context: ParentChildControlContext,
        *,
        actor_type: str,
        actor_id: str,
        run_id: str | None,
    ) -> None:
        # Board/user operations remain the human override path.
        if actor_type != "agent":
            return
        parent = context.parent
        if parent.get("assigneeAgentId") != actor_id:
            raise ParentChildControlDenied(
                "Only the parent assignee Agent can control its child issues"
            )
        if not await self._heartbeat.is_active_parent_run(
            parent["id"],
            run_id,
            expected_org_id=parent["orgId"],
            expected_agent_id=actor_id,
        ):
            raise ParentChildControlDenied(
                "Child control requires the active parent Run"
            )
