from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import OrgMembership


async def get_org_membership(
    session: AsyncSession,
    *,
    org_id: str,
    principal_type: str,
    principal_id: str,
) -> OrgMembership | None:
    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.principal_type == principal_type,
            OrgMembership.principal_id == principal_id,
        )
    )
    return result.scalar_one_or_none()


async def get_org_membership_by_id(
    session: AsyncSession, org_id: str, membership_id: str
) -> OrgMembership | None:
    result = await session.execute(
        select(OrgMembership).where(
            OrgMembership.org_id == org_id,
            OrgMembership.id == membership_id,
        )
    )
    return result.scalar_one_or_none()


async def list_org_memberships(
    session: AsyncSession, org_id: str
) -> Sequence[OrgMembership]:
    result = await session.execute(
        select(OrgMembership)
        .where(OrgMembership.org_id == org_id)
        .order_by(OrgMembership.created_at.desc(), OrgMembership.id.desc())
    )
    return result.scalars().all()


async def list_principal_org_memberships(
    session: AsyncSession,
    *,
    principal_type: str,
    principal_id: str,
    status: str | None = None,
) -> Sequence[OrgMembership]:
    statement = select(OrgMembership).where(
        OrgMembership.principal_type == principal_type,
        OrgMembership.principal_id == principal_id,
    )
    if status is not None:
        statement = statement.where(OrgMembership.status == status)
    result = await session.execute(
        statement.order_by(OrgMembership.created_at.desc(), OrgMembership.id.desc())
    )
    return result.scalars().all()


async def ensure_org_membership_row(
    session: AsyncSession, fields: Mapping[str, Any]
) -> OrgMembership:
    values = dict(fields)
    index_elements = [
        OrgMembership.org_id,
        OrgMembership.principal_type,
        OrgMembership.principal_id,
    ]
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        await session.execute(
            sqlite_insert(OrgMembership)
            .values(**values)
            .on_conflict_do_nothing(index_elements=index_elements)
        )
    elif dialect == "postgresql":
        await session.execute(
            postgresql_insert(OrgMembership)
            .values(**values)
            .on_conflict_do_nothing(index_elements=index_elements)
        )
    else:
        existing = await get_org_membership(
            session,
            org_id=str(values["org_id"]),
            principal_type=str(values["principal_type"]),
            principal_id=str(values["principal_id"]),
        )
        if existing is None:
            session.add(OrgMembership(**values))
            await session.flush()

    row = await get_org_membership(
        session,
        org_id=str(values["org_id"]),
        principal_type=str(values["principal_type"]),
        principal_id=str(values["principal_id"]),
    )
    if row is None:
        raise RuntimeError("Failed to ensure organization membership")
    return row


async def update_org_membership(
    session: AsyncSession, membership_id: str, fields: Mapping[str, Any]
) -> OrgMembership | None:
    result = await session.execute(
        update(OrgMembership)
        .where(OrgMembership.id == membership_id)
        .values(**dict(fields))
        .returning(OrgMembership)
    )
    return result.scalar_one_or_none()
