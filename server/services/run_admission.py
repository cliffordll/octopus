from __future__ import annotations

from .heartbeat import HeartbeatService


class DirectRunCreationDenied(Exception):
    """Raised when a runtime actor tries to create another Run directly."""


class RunAdoptionDenied(Exception):
    """Raised when an agent cannot bind an Issue to its current Run."""


class RunAdmissionPolicy:
    """Central policy for direct Run creation and current-Run adoption."""

    def __init__(self, heartbeat: HeartbeatService) -> None:
        self._heartbeat = heartbeat

    @staticmethod
    def require_direct_creation_authority(*, actor_type: str) -> None:
        if actor_type == "agent":
            raise DirectRunCreationDenied(
                "Agent cannot create Runs directly; use the current Run"
            )

    async def checkout_run_id(
        self,
        *,
        issue_id: str,
        requested_agent_id: str,
        actor_type: str,
        actor_id: str,
        actor_run_id: str | None,
    ) -> str | None:
        if actor_type != "agent":
            return None
        if actor_id != requested_agent_id:
            raise RunAdoptionDenied("Agent cannot checkout for another agent")
        if not actor_run_id:
            raise RunAdoptionDenied("Agent checkout requires an active current Run")

        run = await self._heartbeat.get(actor_run_id)
        if run is None or run["status"] != "running" or run["agentId"] != actor_id:
            raise RunAdoptionDenied(
                "Agent checkout requires its own active current Run"
            )
        bound_issue_id = run.get("issueId")
        if bound_issue_id is not None and bound_issue_id != issue_id:
            raise RunAdoptionDenied("Current Run is already bound to another Issue")
        return actor_run_id
