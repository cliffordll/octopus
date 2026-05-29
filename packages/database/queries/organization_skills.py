from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import AgentEnabledSkill, OrganizationSkill


async def list_organization_skills(
    session: AsyncSession, org_id: str
) -> Sequence[OrganizationSkill]:
    result = await session.execute(
        select(OrganizationSkill)
        .where(OrganizationSkill.org_id == org_id)
        .order_by(OrganizationSkill.name, OrganizationSkill.created_at)
    )
    return result.scalars().all()


async def get_organization_skill(
    session: AsyncSession, org_id: str, skill_id: str
) -> OrganizationSkill | None:
    result = await session.execute(
        select(OrganizationSkill).where(
            OrganizationSkill.org_id == org_id,
            OrganizationSkill.id == skill_id,
        )
    )
    return result.scalar_one_or_none()


async def get_organization_skill_by_key(
    session: AsyncSession, org_id: str, key: str
) -> OrganizationSkill | None:
    result = await session.execute(
        select(OrganizationSkill).where(
            OrganizationSkill.org_id == org_id,
            OrganizationSkill.key == key,
        )
    )
    return result.scalar_one_or_none()


async def create_organization_skill(
    session: AsyncSession, fields: Mapping[str, Any]
) -> OrganizationSkill:
    row = OrganizationSkill(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_organization_skill(
    session: AsyncSession,
    org_id: str,
    skill_id: str,
    fields: Mapping[str, Any],
) -> OrganizationSkill | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(OrganizationSkill)
        .where(
            OrganizationSkill.org_id == org_id,
            OrganizationSkill.id == skill_id,
        )
        .values(**values)
        .returning(OrganizationSkill)
    )
    return result.scalar_one_or_none()


async def delete_organization_skill(
    session: AsyncSession, org_id: str, skill_id: str
) -> OrganizationSkill | None:
    result = await session.execute(
        delete(OrganizationSkill)
        .where(
            OrganizationSkill.org_id == org_id,
            OrganizationSkill.id == skill_id,
        )
        .returning(OrganizationSkill)
    )
    return result.scalar_one_or_none()


async def delete_enabled_skill_key(
    session: AsyncSession, org_id: str, skill_key: str
) -> None:
    await session.execute(
        delete(AgentEnabledSkill).where(
            AgentEnabledSkill.org_id == org_id,
            AgentEnabledSkill.skill_key == skill_key,
        )
    )
