from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import InstanceUserRoleGrant, PrincipalPermissionGrant


async def has_instance_user_role(
    session: AsyncSession, *, user_id: str, role: str
) -> bool:
    result = await session.execute(
        select(InstanceUserRoleGrant.id).where(
            InstanceUserRoleGrant.user_id == user_id,
            InstanceUserRoleGrant.role == role,
        )
    )
    return result.scalar_one_or_none() is not None


async def ensure_instance_user_role(
    session: AsyncSession, *, user_id: str, role: str
) -> InstanceUserRoleGrant:
    values = {"user_id": user_id, "role": role}
    index_elements = [InstanceUserRoleGrant.user_id, InstanceUserRoleGrant.role]
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        await session.execute(
            sqlite_insert(InstanceUserRoleGrant)
            .values(**values)
            .on_conflict_do_nothing(index_elements=index_elements)
        )
    elif dialect == "postgresql":
        await session.execute(
            postgresql_insert(InstanceUserRoleGrant)
            .values(**values)
            .on_conflict_do_nothing(index_elements=index_elements)
        )
    elif not await has_instance_user_role(session, user_id=user_id, role=role):
        session.add(InstanceUserRoleGrant(**values))
        await session.flush()

    result = await session.execute(
        select(InstanceUserRoleGrant).where(
            InstanceUserRoleGrant.user_id == user_id,
            InstanceUserRoleGrant.role == role,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise RuntimeError("Failed to ensure instance user role")
    return row


async def list_principal_permission_grants(
    session: AsyncSession,
    *,
    org_id: str,
    principal_type: str,
    principal_id: str,
) -> Sequence[PrincipalPermissionGrant]:
    result = await session.execute(
        select(PrincipalPermissionGrant)
        .where(
            PrincipalPermissionGrant.org_id == org_id,
            PrincipalPermissionGrant.principal_type == principal_type,
            PrincipalPermissionGrant.principal_id == principal_id,
        )
        .order_by(PrincipalPermissionGrant.permission_key)
    )
    return result.scalars().all()


async def replace_principal_permission_grants(
    session: AsyncSession,
    *,
    org_id: str,
    principal_type: str,
    principal_id: str,
    grants: Sequence[Mapping[str, Any]],
    granted_by_user_id: str | None,
) -> None:
    await session.execute(
        delete(PrincipalPermissionGrant).where(
            PrincipalPermissionGrant.org_id == org_id,
            PrincipalPermissionGrant.principal_type == principal_type,
            PrincipalPermissionGrant.principal_id == principal_id,
        )
    )
    for grant in grants:
        session.add(
            PrincipalPermissionGrant(
                org_id=org_id,
                principal_type=principal_type,
                principal_id=principal_id,
                permission_key=str(grant["permission_key"]),
                scope=grant.get("scope"),
                granted_by_user_id=granted_by_user_id,
            )
        )
    await session.flush()
