from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.run_intelligence import RunIntelligenceService
from .database import get_session


def get_run_intelligence_service(
    session: AsyncSession = Depends(get_session),
) -> RunIntelligenceService:
    return RunIntelligenceService(session)
