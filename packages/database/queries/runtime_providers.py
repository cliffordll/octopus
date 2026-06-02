from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import RuntimeModel, RuntimeProvider


async def list_runtime_providers(
    session: AsyncSession, org_id: str, runtime_type: str
) -> Sequence[RuntimeProvider]:
    result = await session.execute(
        select(RuntimeProvider)
        .where(
            RuntimeProvider.org_id == org_id,
            RuntimeProvider.runtime_type == runtime_type,
        )
        .order_by(RuntimeProvider.name, RuntimeProvider.provider_id)
    )
    return result.scalars().all()


async def get_runtime_provider(
    session: AsyncSession, org_id: str, runtime_type: str, provider_id: str
) -> RuntimeProvider | None:
    result = await session.execute(
        select(RuntimeProvider).where(
            RuntimeProvider.org_id == org_id,
            RuntimeProvider.runtime_type == runtime_type,
            RuntimeProvider.provider_id == provider_id,
        )
    )
    return result.scalar_one_or_none()


async def create_runtime_provider(
    session: AsyncSession, fields: Mapping[str, Any]
) -> RuntimeProvider:
    row = RuntimeProvider(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_runtime_provider(
    session: AsyncSession,
    org_id: str,
    runtime_type: str,
    provider_id: str,
    fields: Mapping[str, Any],
) -> RuntimeProvider | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(RuntimeProvider)
        .where(
            RuntimeProvider.org_id == org_id,
            RuntimeProvider.runtime_type == runtime_type,
            RuntimeProvider.provider_id == provider_id,
        )
        .values(**values)
        .returning(RuntimeProvider)
    )
    return result.scalar_one_or_none()


async def delete_runtime_provider(
    session: AsyncSession, org_id: str, runtime_type: str, provider_id: str
) -> RuntimeProvider | None:
    result = await session.execute(
        delete(RuntimeProvider)
        .where(
            RuntimeProvider.org_id == org_id,
            RuntimeProvider.runtime_type == runtime_type,
            RuntimeProvider.provider_id == provider_id,
        )
        .returning(RuntimeProvider)
    )
    return result.scalar_one_or_none()


async def delete_runtime_models_for_provider(
    session: AsyncSession, org_id: str, runtime_type: str, provider_id: str
) -> None:
    await session.execute(
        delete(RuntimeModel).where(
            RuntimeModel.org_id == org_id,
            RuntimeModel.runtime_type == runtime_type,
            RuntimeModel.provider_id == provider_id,
        )
    )


async def list_runtime_models(
    session: AsyncSession, org_id: str, runtime_type: str, provider_id: str
) -> Sequence[RuntimeModel]:
    result = await session.execute(
        select(RuntimeModel)
        .where(
            RuntimeModel.org_id == org_id,
            RuntimeModel.runtime_type == runtime_type,
            RuntimeModel.provider_id == provider_id,
        )
        .order_by(RuntimeModel.display_name, RuntimeModel.model_id)
    )
    return result.scalars().all()


async def get_runtime_model(
    session: AsyncSession,
    org_id: str,
    runtime_type: str,
    provider_id: str,
    model_id: str,
) -> RuntimeModel | None:
    result = await session.execute(
        select(RuntimeModel).where(
            RuntimeModel.org_id == org_id,
            RuntimeModel.runtime_type == runtime_type,
            RuntimeModel.provider_id == provider_id,
            RuntimeModel.model_id == model_id,
        )
    )
    return result.scalar_one_or_none()


async def create_runtime_model(
    session: AsyncSession, fields: Mapping[str, Any]
) -> RuntimeModel:
    row = RuntimeModel(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def update_runtime_model(
    session: AsyncSession,
    org_id: str,
    runtime_type: str,
    provider_id: str,
    model_id: str,
    fields: Mapping[str, Any],
) -> RuntimeModel | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(RuntimeModel)
        .where(
            RuntimeModel.org_id == org_id,
            RuntimeModel.runtime_type == runtime_type,
            RuntimeModel.provider_id == provider_id,
            RuntimeModel.model_id == model_id,
        )
        .values(**values)
        .returning(RuntimeModel)
    )
    return result.scalar_one_or_none()


async def delete_runtime_model(
    session: AsyncSession,
    org_id: str,
    runtime_type: str,
    provider_id: str,
    model_id: str,
) -> RuntimeModel | None:
    result = await session.execute(
        delete(RuntimeModel)
        .where(
            RuntimeModel.org_id == org_id,
            RuntimeModel.runtime_type == runtime_type,
            RuntimeModel.provider_id == provider_id,
            RuntimeModel.model_id == model_id,
        )
        .returning(RuntimeModel)
    )
    return result.scalar_one_or_none()
