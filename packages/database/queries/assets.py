from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Asset


async def create_asset(session: AsyncSession, fields: Mapping[str, Any]) -> Asset:
    row = Asset(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def get_asset_by_id(session: AsyncSession, asset_id: str) -> Asset | None:
    return await session.get(Asset, asset_id)
