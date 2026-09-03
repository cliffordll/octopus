from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Role


async def get_role(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: str,
    principal_type: str,
    principal_id: str,
) -> Role | None:
    result = await session.execute(
        select(Role).where(
            Role.scope_type == scope_type,
            Role.scope_id == scope_id,
            Role.principal_type == principal_type,
            Role.principal_id == principal_id,
        )
    )
    return result.scalar_one_or_none()


async def get_role_by_id(
    session: AsyncSession, *, scope_type: str, scope_id: str, role_id: str
) -> Role | None:
    result = await session.execute(
        select(Role).where(
            Role.scope_type == scope_type,
            Role.scope_id == scope_id,
            Role.id == role_id,
        )
    )
    return result.scalar_one_or_none()


async def list_scope_roles(
    session: AsyncSession, *, scope_type: str, scope_id: str
) -> Sequence[Role]:
    result = await session.execute(
        select(Role)
        .where(Role.scope_type == scope_type, Role.scope_id == scope_id)
        .order_by(Role.created_at.desc(), Role.id.desc())
    )
    return result.scalars().all()


async def list_principal_roles(
    session: AsyncSession,
    *,
    principal_type: str,
    principal_id: str,
    scope_type: str | None = None,
    status: str | None = None,
) -> Sequence[Role]:
    statement = select(Role).where(
        Role.principal_type == principal_type,
        Role.principal_id == principal_id,
    )
    if scope_type is not None:
        statement = statement.where(Role.scope_type == scope_type)
    if status is not None:
        statement = statement.where(Role.status == status)
    result = await session.execute(
        statement.order_by(Role.created_at.desc(), Role.id.desc())
    )
    return result.scalars().all()


async def ensure_role(session: AsyncSession, fields: Mapping[str, Any]) -> Role:
    values = dict(fields)
    index_elements = [
        Role.scope_type,
        Role.scope_id,
        Role.principal_type,
        Role.principal_id,
    ]
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        await session.execute(
            sqlite_insert(Role)
            .values(**values)
            .on_conflict_do_nothing(index_elements=index_elements)
        )
    elif dialect == "postgresql":
        await session.execute(
            postgresql_insert(Role)
            .values(**values)
            .on_conflict_do_nothing(index_elements=index_elements)
        )
    else:
        existing = await get_role(
            session,
            scope_type=str(values["scope_type"]),
            scope_id=str(values["scope_id"]),
            principal_type=str(values["principal_type"]),
            principal_id=str(values["principal_id"]),
        )
        if existing is None:
            session.add(Role(**values))
            await session.flush()

    row = await get_role(
        session,
        scope_type=str(values["scope_type"]),
        scope_id=str(values["scope_id"]),
        principal_type=str(values["principal_type"]),
        principal_id=str(values["principal_id"]),
    )
    if row is None:
        raise RuntimeError("Failed to ensure role")
    return row


async def update_role(
    session: AsyncSession, role_id: str, fields: Mapping[str, Any]
) -> Role | None:
    result = await session.execute(
        update(Role).where(Role.id == role_id).values(**dict(fields)).returning(Role)
    )
    return result.scalar_one_or_none()
