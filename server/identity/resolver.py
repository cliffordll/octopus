from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.access import (
    has_instance_user_role,
    list_principal_permission_grants,
)
from server.membership import MemberAccessService, MemberService

from .context import IdentityContext
from .principal import PrincipalRef


class IdentityContextResolver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._member_access = MemberAccessService(MemberService(session))

    async def resolve(
        self,
        *,
        actor_type: str,
        actor_id: str,
        org_id: str | None,
        source: str,
        run_id: str | None = None,
    ) -> IdentityContext:
        principal = PrincipalRef.from_actor(actor_type, actor_id)
        if principal.type == "system":
            raise ValueError(
                "System request contexts must use SystemIdentityContextFactory"
            )

        membership = None
        grants = []
        if org_id is not None:
            membership = await self._member_access.find_active(org_id, principal)
            grants = list(
                await list_principal_permission_grants(
                    self._session,
                    org_id=org_id,
                    principal_type=principal.membership_type(),
                    principal_id=principal.id,
                )
            )

        is_instance_admin = principal.type == "user" and await has_instance_user_role(
            self._session,
            user_id=principal.id,
            role="instance_admin",
        )
        return IdentityContext(
            principal=principal,
            org_id=org_id,
            membership_id=membership.id if membership is not None else None,
            membership_role=(
                membership.membership_role if membership is not None else None
            ),
            permissions=frozenset(grant.permission_key for grant in grants),
            permission_scopes={grant.permission_key: grant.scope for grant in grants},
            source=source,
            run_id=run_id,
            is_instance_admin=is_instance_admin,
        )
