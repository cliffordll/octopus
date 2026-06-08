from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from ..services.activity import ActivityService


async def get_activity_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncIterator[ActivityService]:
    yield ActivityService(session)
