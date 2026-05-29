from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.resources import ResourceService
from .database import get_session


def get_resource_service(
    session: AsyncSession = Depends(get_session),
) -> ResourceService:
    return ResourceService(session)
