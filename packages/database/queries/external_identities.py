from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import ExternalIdentity


async def get_external_identity(
    session: AsyncSession, issuer: str, subject: str
) -> ExternalIdentity | None:
    result = await session.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.issuer == issuer,
            ExternalIdentity.subject == subject,
        )
    )
    return result.scalar_one_or_none()


async def ensure_external_identity(
    session: AsyncSession, *, issuer: str, subject: str, user_id: str
) -> ExternalIdentity:
    values = {"issuer": issuer, "subject": subject, "user_id": user_id}
    dialect = session.get_bind().dialect.name
    statement = None
    if dialect == "sqlite":
        statement = (
            sqlite_insert(ExternalIdentity)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[ExternalIdentity.issuer, ExternalIdentity.subject]
            )
        )
    elif dialect == "postgresql":
        statement = (
            postgresql_insert(ExternalIdentity)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[ExternalIdentity.issuer, ExternalIdentity.subject]
            )
        )
    if statement is not None:
        await session.execute(statement)
    elif await get_external_identity(session, issuer, subject) is None:
        session.add(ExternalIdentity(**values))
        await session.flush()
    row = await get_external_identity(session, issuer, subject)
    if row is None or row.user_id != user_id:
        raise ValueError("External identity is already bound to another user")
    await session.execute(
        update(ExternalIdentity)
        .where(ExternalIdentity.id == row.id)
        .values(last_verified_at=datetime.now(UTC))
    )
    return row
