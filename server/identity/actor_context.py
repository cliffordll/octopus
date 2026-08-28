from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.access import has_instance_user_role
from packages.database.queries.organization_memberships import (
    list_principal_org_memberships,
)

if TYPE_CHECKING:
    from server.auth.contracts import AuthResult


class AuthenticatedActorProjector:
    """Project a verified identity into the legacy request Actor contract."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def project(self, result: AuthResult) -> dict[str, Any]:
        principal = result.principal
        actor: dict[str, Any] = {
            "type": principal.type,
            "id": principal.id,
            "orgId": result.org_id,
            "source": result.source,
        }
        if principal.type == "agent":
            actor["agentId"] = principal.id
            actor["runId"] = result.run_id
            actor["orgIds"] = [result.org_id] if result.org_id else []
            return actor

        if principal.type != "user":
            raise ValueError("Authenticated request Actor must be a User or Agent")

        actor["userId"] = principal.id
        memberships = await list_principal_org_memberships(
            self._session,
            principal_type="user",
            principal_id=principal.id,
            status="active",
        )
        membership_org_ids = {membership.org_id for membership in memberships}
        if result.org_id is not None:
            membership_org_ids.intersection_update({result.org_id})
        actor["orgIds"] = sorted(membership_org_ids)
        actor["isInstanceAdmin"] = await has_instance_user_role(
            self._session,
            user_id=principal.id,
            role="instance_admin",
        )
        return actor
