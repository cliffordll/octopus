from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Invite


async def create_invite(session: AsyncSession, fields: Mapping[str, Any]) -> Invite:
    row = Invite(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def get_invite_by_token_hash(
    session: AsyncSession, token_hash: str
) -> Invite | None:
    result = await session.execute(
        select(Invite).where(Invite.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def get_invite_by_id(session: AsyncSession, invite_id: str) -> Invite | None:
    result = await session.execute(select(Invite).where(Invite.id == invite_id))
    return result.scalar_one_or_none()


async def list_org_invites(session: AsyncSession, org_id: str) -> Sequence[Invite]:
    result = await session.execute(
        select(Invite).where(Invite.org_id == org_id).order_by(Invite.created_at.desc())
    )
    return result.scalars().all()


async def update_invite(
    session: AsyncSession, invite_id: str, fields: Mapping[str, Any]
) -> Invite | None:
    result = await session.execute(
        update(Invite)
        .where(Invite.id == invite_id)
        .values(**dict(fields))
        .returning(Invite)
    )
    return result.scalar_one_or_none()
