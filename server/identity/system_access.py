from __future__ import annotations

from server.access import AccessPolicyService

from .context import IdentityContext
from .system_context import SystemIdentityContextFactory


class SystemOperationAccess:
    """Create and authorize a scoped identity for one internal operation."""

    def __init__(
        self,
        *,
        contexts: SystemIdentityContextFactory | None = None,
        policy: AccessPolicyService | None = None,
    ) -> None:
        self._contexts = contexts or SystemIdentityContextFactory()
        self._policy = policy or AccessPolicyService()

    def require(
        self,
        *,
        system_id: str,
        org_id: str,
        permission: str,
        reason: str,
        entity_type: str,
        entity_id: str,
    ) -> IdentityContext:
        context = self._contexts.create(
            system_id=system_id,
            org_id=org_id,
            reason=reason,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        self._policy.require_permission(context, org_id, permission)
        return context
