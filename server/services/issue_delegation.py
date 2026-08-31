from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.roles import get_role


class IssueDelegationDenied(PermissionError):
    """Raised when an Agent delegates work outside its reporting line."""


class IssueDelegationAuthorizer:
    """Enforce organization reporting lines for Agent-created child issues."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def authorize(
        self,
        org_id: str,
        children: Sequence[Mapping[str, object]],
        *,
        actor_type: str,
        actor_id: str,
    ) -> None:
        # Human board operations remain the explicit management override path.
        if actor_type != "agent":
            return

        manager = await get_role(
            self._session,
            scope_type="organization",
            scope_id=org_id,
            principal_type="agent",
            principal_id=actor_id,
        )
        if manager is None or manager.status != "active":
            raise IssueDelegationDenied(
                "Agent delegation requires an active organization role"
            )

        for child in children:
            principal_type, principal_id = self._assignee(child)
            assignee = await get_role(
                self._session,
                scope_type="organization",
                scope_id=org_id,
                principal_type=principal_type,
                principal_id=principal_id,
            )
            if (
                assignee is None
                or assignee.status != "active"
                or assignee.reports_to != manager.id
            ):
                raise IssueDelegationDenied(
                    "Agents can delegate child issues only to their direct reports; "
                    "ask the responsible manager to assign this work"
                )

    @staticmethod
    def _assignee(child: Mapping[str, object]) -> tuple[str, str]:
        agent_id = child.get("assigneeAgentId")
        if isinstance(agent_id, str) and agent_id:
            return "agent", agent_id
        user_id = child.get("assigneeUserId")
        if isinstance(user_id, str) and user_id:
            return "user", user_id
        raise IssueDelegationDenied("Delegated child issue must have an assignee")
