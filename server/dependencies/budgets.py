from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_session
from ..services.budgets import BudgetService


async def get_budget_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncIterator[BudgetService]:
    yield BudgetService(session)
