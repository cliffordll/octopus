from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.permissions import list_permissions, replace_permissions
from packages.database.schema import Permission
from packages.shared.constants.access import (
    ACCESS_SCOPE_TYPES,
    PERMISSION_KEYS,
    AccessScopeType,
    PermissionKey,
)
from server.identity.principal import PrincipalRef


@dataclass(frozen=True, slots=True)
class PermissionSpec:
    permission: PermissionKey
    constraints: dict[str, Any] | None = None


class PermissionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        scope_type: AccessScopeType,
        scope_id: str,
        principal: PrincipalRef,
    ) -> list[Permission]:
        return list(
            await list_permissions(
                self._session,
                scope_type=scope_type,
                scope_id=scope_id,
                principal_type=principal.access_type(),
                principal_id=principal.id,
            )
        )

    async def replace(
        self,
        scope_type: AccessScopeType,
        scope_id: str,
        principal: PrincipalRef,
        permissions: Sequence[PermissionSpec],
        *,
        granted_by_user_id: str | None,
    ) -> None:
        if scope_type not in ACCESS_SCOPE_TYPES:
            raise ValueError(f"Unsupported permission scope: {scope_type}")
        principal_type = principal.access_type()
        for permission in permissions:
            if permission.permission not in PERMISSION_KEYS:
                raise ValueError(f"Unsupported permission: {permission.permission}")
        await replace_permissions(
            self._session,
            scope_type=scope_type,
            scope_id=scope_id,
            principal_type=principal_type,
            principal_id=principal.id,
            permissions=[
                {
                    "permission_key": permission.permission,
                    "constraints": permission.constraints,
                }
                for permission in permissions
            ],
            granted_by_user_id=granted_by_user_id,
        )
