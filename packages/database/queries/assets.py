from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Asset


async def create_asset(session: AsyncSession, fields: Mapping[str, Any]) -> Asset:
    row = Asset(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def get_asset_by_id(session: AsyncSession, asset_id: str) -> Asset | None:
    return await session.get(Asset, asset_id)


async def get_asset_by_sha256(
    session: AsyncSession, org_id: str, sha256: str
) -> Asset | None:
    """Return an existing asset with identical content for the org, if any.

    Lets callers reuse a stored object instead of re-archiving the same bytes
    into a brand-new asset on every capture."""
    if not sha256:
        return None
    result = await session.execute(
        select(Asset)
        .where(Asset.org_id == org_id, Asset.sha256 == sha256)
        .order_by(Asset.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
