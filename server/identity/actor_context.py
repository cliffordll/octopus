from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.roles import list_principal_roles
from packages.shared.constants.access import INSTANCE_SCOPE_ID

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
        roles = await list_principal_roles(
            self._session,
            principal_type="user",
            principal_id=principal.id,
            scope_type="organization",
            status="active",
        )
        organization_ids = {role.scope_id for role in roles}
        if result.org_id is not None:
            organization_ids.intersection_update({result.org_id})
        actor["orgIds"] = sorted(organization_ids)
        root_roles = await list_principal_roles(
            self._session,
            principal_type="user",
            principal_id=principal.id,
            scope_type="instance",
            status="active",
        )
        actor["isRoot"] = any(
            role.scope_id == INSTANCE_SCOPE_ID and role.role == "root"
            for role in root_roles
        )
        return actor
