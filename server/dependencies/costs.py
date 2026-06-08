from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from ..services.costs import CostService


async def get_cost_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncIterator[CostService]:
    yield CostService(session)
