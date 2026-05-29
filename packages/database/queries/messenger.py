from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import MessengerThreadUserState


async def get_thread_user_state(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread_key: str,
) -> MessengerThreadUserState | None:
    result = await session.execute(
        select(MessengerThreadUserState).where(
            MessengerThreadUserState.org_id == org_id,
            MessengerThreadUserState.user_id == user_id,
            MessengerThreadUserState.thread_key == thread_key,
        )
    )
    return result.scalar_one_or_none()


async def upsert_thread_user_state(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    thread_key: str,
    last_read_at: datetime,
) -> MessengerThreadUserState:
    row = await get_thread_user_state(
        session, org_id=org_id, user_id=user_id, thread_key=thread_key
    )
    now = datetime.now(UTC)
    if row is None:
        row = MessengerThreadUserState(
            org_id=org_id,
            user_id=user_id,
            thread_key=thread_key,
            last_read_at=last_read_at,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.last_read_at = last_read_at
        row.updated_at = now
    await session.flush()
    return row
