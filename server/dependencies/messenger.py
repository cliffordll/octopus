from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.messenger import MessengerService
from .database import get_session


def get_messenger_service(
    session: AsyncSession = Depends(get_session),
) -> MessengerService:
    return MessengerService(session)
