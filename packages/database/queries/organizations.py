from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Organization


async def list_organizations(session: AsyncSession) -> Sequence[Organization]:
    result = await session.execute(
        select(Organization).order_by(Organization.created_at)
    )
    return result.scalars().all()


async def get_organization_by_id(
    session: AsyncSession, organization_id: str
) -> Organization | None:
    result = await session.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_organization_by_url_key(
    session: AsyncSession, url_key: str
) -> Organization | None:
    result = await session.execute(
        select(Organization).where(Organization.url_key == url_key)
    )
    return result.scalar_one_or_none()


async def create_organization(
    session: AsyncSession,
    *,
    id: str,
    url_key: str,
    name: str,
    description: str | None = None,
    issue_prefix: str,
    budget_monthly_cents: int = 0,
    default_chat_issue_creation_mode: str = "manual_approval",
    brand_color: str | None = None,
    require_board_approval_for_new_agents: bool = True,
) -> Organization:
    row = Organization(
        id=id,
        url_key=url_key,
        name=name,
        description=description,
        issue_prefix=issue_prefix,
        budget_monthly_cents=budget_monthly_cents,
        default_chat_issue_creation_mode=default_chat_issue_creation_mode,
        brand_color=brand_color,
        require_board_approval_for_new_agents=require_board_approval_for_new_agents,
    )
    session.add(row)
    await session.flush()
    return row


async def increment_issue_counter(
    session: AsyncSession, organization_id: str
) -> tuple[int, str] | None:
    """Atomically bump ``organizations.issue_counter`` and return ``(new_counter, prefix)``.

    Mirrors upstream ``services/issues.ts:797-804``: the UPDATE ... RETURNING
    bumps the counter and the caller composes ``f"{prefix}-{counter}"`` as the
    issue identifier. Returns ``None`` when the organization is missing.
    """

    result = await session.execute(
        update(Organization)
        .where(Organization.id == organization_id)
        .values(issue_counter=Organization.issue_counter + 1)
        .returning(Organization.issue_counter, Organization.issue_prefix)
    )
    row = result.first()
    if row is None:
        return None
    return int(row[0]), str(row[1])


async def update_organization(
    session: AsyncSession,
    organization_id: str,
    fields: Mapping[str, Any],
) -> Organization | None:
    if not fields:
        return await get_organization_by_id(session, organization_id)

    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)

    result = await session.execute(
        update(Organization)
        .where(Organization.id == organization_id)
        .values(**values)
        .returning(Organization)
    )
    return result.scalar_one_or_none()
