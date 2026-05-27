from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.agents import AgentService
from .database import get_session


def get_agent_service(session: AsyncSession = Depends(get_session)) -> AgentService:
    return AgentService(session)
