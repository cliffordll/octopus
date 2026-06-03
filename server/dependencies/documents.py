from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.documents import DocumentService
from .database import get_session


def get_document_service(
    session: AsyncSession = Depends(get_session),
) -> DocumentService:
    return DocumentService(session)
