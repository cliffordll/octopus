from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.access import (
    list_principal_permission_grants,
    replace_principal_permission_grants,
)
from packages.database.schema import PrincipalPermissionGrant
from packages.shared.constants.access import PERMISSION_KEYS, PermissionKey
from server.identity.principal import PrincipalRef


@dataclass(frozen=True, slots=True)
class PermissionGrantSpec:
    permission: PermissionKey
    scope: dict[str, Any] | None = None


class PrincipalGrantService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self, org_id: str, principal: PrincipalRef
    ) -> list[PrincipalPermissionGrant]:
        return list(
            await list_principal_permission_grants(
                self._session,
                org_id=org_id,
                principal_type=principal.membership_type(),
                principal_id=principal.id,
            )
        )

    async def replace(
        self,
        org_id: str,
        principal: PrincipalRef,
        grants: Sequence[PermissionGrantSpec],
        *,
        granted_by_user_id: str | None,
    ) -> None:
        principal_type = principal.membership_type()
        for grant in grants:
            if grant.permission not in PERMISSION_KEYS:
                raise ValueError(f"Unsupported permission: {grant.permission}")
        await replace_principal_permission_grants(
            self._session,
            org_id=org_id,
            principal_type=principal_type,
            principal_id=principal.id,
            grants=[
                {"permission_key": grant.permission, "scope": grant.scope}
                for grant in grants
            ],
            granted_by_user_id=granted_by_user_id,
        )
