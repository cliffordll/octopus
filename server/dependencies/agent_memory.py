from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.agent_memory import AgentMemoryService
from .database import get_session


def get_agent_memory_service(
    session: AsyncSession = Depends(get_session),
) -> AgentMemoryService:
    return AgentMemoryService(session)
