from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.heartbeat import HeartbeatService
from .database import get_session


def get_heartbeat_service(
    session: AsyncSession = Depends(get_session),
) -> HeartbeatService:
    return HeartbeatService(session)
