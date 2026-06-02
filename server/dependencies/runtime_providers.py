from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.runtime_providers import RuntimeProviderService
from .database import get_session


def get_runtime_provider_service(
    session: AsyncSession = Depends(get_session),
) -> RuntimeProviderService:
    return RuntimeProviderService(session)
