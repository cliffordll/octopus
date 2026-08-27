from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import ExternalUserBinding


async def get_external_user_binding(
    session: AsyncSession, issuer: str, subject: str
) -> ExternalUserBinding | None:
    result = await session.execute(
        select(ExternalUserBinding).where(
            ExternalUserBinding.issuer == issuer,
            ExternalUserBinding.subject == subject,
        )
    )
    return result.scalar_one_or_none()


async def ensure_external_user_binding(
    session: AsyncSession, *, issuer: str, subject: str, local_user_id: str
) -> ExternalUserBinding:
    values = {"issuer": issuer, "subject": subject, "local_user_id": local_user_id}
    dialect = session.get_bind().dialect.name
    statement = None
    if dialect == "sqlite":
        statement = (
            sqlite_insert(ExternalUserBinding)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[ExternalUserBinding.issuer, ExternalUserBinding.subject]
            )
        )
    elif dialect == "postgresql":
        statement = (
            postgresql_insert(ExternalUserBinding)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[ExternalUserBinding.issuer, ExternalUserBinding.subject]
            )
        )
    if statement is not None:
        await session.execute(statement)
    elif await get_external_user_binding(session, issuer, subject) is None:
        session.add(ExternalUserBinding(**values))
        await session.flush()
    row = await get_external_user_binding(session, issuer, subject)
    if row is None or row.local_user_id != local_user_id:
        raise ValueError("External identity is already bound to another user")
    await session.execute(
        update(ExternalUserBinding)
        .where(ExternalUserBinding.id == row.id)
        .values(last_verified_at=datetime.now(UTC))
    )
    return row
