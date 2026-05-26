from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.issues import IssueService
from .database import get_session


def get_issue_service(session: AsyncSession = Depends(get_session)) -> IssueService:
    return IssueService(session)
