from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Permission


async def list_permissions(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: str,
    principal_type: str,
    principal_id: str,
) -> Sequence[Permission]:
    result = await session.execute(
        select(Permission)
        .where(
            Permission.scope_type == scope_type,
            Permission.scope_id == scope_id,
            Permission.principal_type == principal_type,
            Permission.principal_id == principal_id,
        )
        .order_by(Permission.permission_key)
    )
    return result.scalars().all()


async def replace_permissions(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: str,
    principal_type: str,
    principal_id: str,
    permissions: Sequence[Mapping[str, Any]],
    granted_by_user_id: str | None,
) -> None:
    await session.execute(
        delete(Permission).where(
            Permission.scope_type == scope_type,
            Permission.scope_id == scope_id,
            Permission.principal_type == principal_type,
            Permission.principal_id == principal_id,
        )
    )
    for permission in permissions:
        session.add(
            Permission(
                scope_type=scope_type,
                scope_id=scope_id,
                principal_type=principal_type,
                principal_id=principal_id,
                permission_key=str(permission["permission_key"]),
                constraints=permission.get("constraints"),
                granted_by_user_id=granted_by_user_id,
            )
        )
    await session.flush()
