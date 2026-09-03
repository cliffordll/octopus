from __future__ import annotations

from collections.abc import Mapping

from packages.shared.types.issue import IssueDetail
from server.identity import IdentityContext

from .errors import AccessDeniedError
from .policy import AccessPolicyService


class IssueUpdateAccessPolicy:
    """Separates organization task management from assignee execution rights."""

    _HUMAN_EXECUTION_FIELDS = frozenset(
        {"status", "comment", "workProductDeclarations"}
    )
    _HUMAN_EXECUTION_STATUSES = frozenset({"todo", "in_progress", "done", "blocked"})

    def require(
        self,
        context: IdentityContext,
        issue: IssueDetail,
        payload: Mapping[str, object],
    ) -> None:
        access = AccessPolicyService()
        access.require_organization_access(context, issue["orgId"])
        if access.has_permission(context, "tasks:assign"):
            return
        if self._is_assigned_human_execution(context, issue, payload):
            return
        raise AccessDeniedError(
            "Only task managers or the assigned Human can update this issue"
        )

    def _is_assigned_human_execution(
        self,
        context: IdentityContext,
        issue: IssueDetail,
        payload: Mapping[str, object],
    ) -> bool:
        if (
            context.principal.type != "user"
            or issue.get("assigneeUserId") != context.principal.id
            or not payload
            or not set(payload).issubset(self._HUMAN_EXECUTION_FIELDS)
        ):
            return False
        status = payload.get("status")
        return status is None or status in self._HUMAN_EXECUTION_STATUSES
