from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import (
    RuntimeGlobalModel,
    RuntimeGlobalProvider,
    RuntimeModel,
    RuntimeModelDefault,
    RuntimeProvider,
)
from ._compat import delete_returning_one, update_returning_one


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


async def list_global_runtime_providers(
    session: AsyncSession, runtime_type: str
) -> Sequence[RuntimeGlobalProvider]:
    result = await session.execute(
        select(RuntimeGlobalProvider)
        .where(RuntimeGlobalProvider.runtime_type == runtime_type)
        .order_by(RuntimeGlobalProvider.name, RuntimeGlobalProvider.provider_id)
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


async def get_global_runtime_provider(
    session: AsyncSession, runtime_type: str, provider_id: str
) -> RuntimeGlobalProvider | None:
    result = await session.execute(
        select(RuntimeGlobalProvider).where(
            RuntimeGlobalProvider.runtime_type == runtime_type,
            RuntimeGlobalProvider.provider_id == provider_id,
        )
    )
    return result.scalar_one_or_none()


async def create_runtime_provider(
    session: AsyncSession, fields: Mapping[str, Any]
) -> RuntimeProvider:
    row = RuntimeProvider(**dict(fields))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def create_global_runtime_provider(
    session: AsyncSession, fields: Mapping[str, Any]
) -> RuntimeGlobalProvider:
    row = RuntimeGlobalProvider(**dict(fields))
    session.add(row)
    await session.flush()
    await session.refresh(row)
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
    return await update_returning_one(
        session,
        RuntimeProvider,
        and_(
            RuntimeProvider.org_id == org_id,
            RuntimeProvider.runtime_type == runtime_type,
            RuntimeProvider.provider_id == provider_id,
        ),
        values,
    )


async def update_global_runtime_provider(
    session: AsyncSession,
    runtime_type: str,
    provider_id: str,
    fields: Mapping[str, Any],
) -> RuntimeGlobalProvider | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        RuntimeGlobalProvider,
        and_(
            RuntimeGlobalProvider.runtime_type == runtime_type,
            RuntimeGlobalProvider.provider_id == provider_id,
        ),
        values,
    )


async def delete_runtime_provider(
    session: AsyncSession, org_id: str, runtime_type: str, provider_id: str
) -> RuntimeProvider | None:
    return await delete_returning_one(
        session,
        RuntimeProvider,
        and_(
            RuntimeProvider.org_id == org_id,
            RuntimeProvider.runtime_type == runtime_type,
            RuntimeProvider.provider_id == provider_id,
        ),
    )


async def delete_global_runtime_provider(
    session: AsyncSession, runtime_type: str, provider_id: str
) -> RuntimeGlobalProvider | None:
    return await delete_returning_one(
        session,
        RuntimeGlobalProvider,
        and_(
            RuntimeGlobalProvider.runtime_type == runtime_type,
            RuntimeGlobalProvider.provider_id == provider_id,
        ),
    )


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


async def delete_global_runtime_models_for_provider(
    session: AsyncSession, runtime_type: str, provider_id: str
) -> None:
    await session.execute(
        delete(RuntimeGlobalModel).where(
            RuntimeGlobalModel.runtime_type == runtime_type,
            RuntimeGlobalModel.provider_id == provider_id,
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


async def list_global_runtime_models(
    session: AsyncSession, runtime_type: str, provider_id: str
) -> Sequence[RuntimeGlobalModel]:
    result = await session.execute(
        select(RuntimeGlobalModel)
        .where(
            RuntimeGlobalModel.runtime_type == runtime_type,
            RuntimeGlobalModel.provider_id == provider_id,
        )
        .order_by(RuntimeGlobalModel.display_name, RuntimeGlobalModel.model_id)
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


async def get_global_runtime_model(
    session: AsyncSession,
    runtime_type: str,
    provider_id: str,
    model_id: str,
) -> RuntimeGlobalModel | None:
    result = await session.execute(
        select(RuntimeGlobalModel).where(
            RuntimeGlobalModel.runtime_type == runtime_type,
            RuntimeGlobalModel.provider_id == provider_id,
            RuntimeGlobalModel.model_id == model_id,
        )
    )
    return result.scalar_one_or_none()


async def create_runtime_model(
    session: AsyncSession, fields: Mapping[str, Any]
) -> RuntimeModel:
    row = RuntimeModel(**dict(fields))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def create_global_runtime_model(
    session: AsyncSession, fields: Mapping[str, Any]
) -> RuntimeGlobalModel:
    row = RuntimeGlobalModel(**dict(fields))
    session.add(row)
    await session.flush()
    await session.refresh(row)
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
    return await update_returning_one(
        session,
        RuntimeModel,
        and_(
            RuntimeModel.org_id == org_id,
            RuntimeModel.runtime_type == runtime_type,
            RuntimeModel.provider_id == provider_id,
            RuntimeModel.model_id == model_id,
        ),
        values,
    )


async def update_global_runtime_model(
    session: AsyncSession,
    runtime_type: str,
    provider_id: str,
    model_id: str,
    fields: Mapping[str, Any],
) -> RuntimeGlobalModel | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        RuntimeGlobalModel,
        and_(
            RuntimeGlobalModel.runtime_type == runtime_type,
            RuntimeGlobalModel.provider_id == provider_id,
            RuntimeGlobalModel.model_id == model_id,
        ),
        values,
    )


async def delete_runtime_model(
    session: AsyncSession,
    org_id: str,
    runtime_type: str,
    provider_id: str,
    model_id: str,
) -> RuntimeModel | None:
    return await delete_returning_one(
        session,
        RuntimeModel,
        and_(
            RuntimeModel.org_id == org_id,
            RuntimeModel.runtime_type == runtime_type,
            RuntimeModel.provider_id == provider_id,
            RuntimeModel.model_id == model_id,
        ),
    )


async def delete_global_runtime_model(
    session: AsyncSession,
    runtime_type: str,
    provider_id: str,
    model_id: str,
) -> RuntimeGlobalModel | None:
    return await delete_returning_one(
        session,
        RuntimeGlobalModel,
        and_(
            RuntimeGlobalModel.runtime_type == runtime_type,
            RuntimeGlobalModel.provider_id == provider_id,
            RuntimeGlobalModel.model_id == model_id,
        ),
    )


async def get_runtime_model_default(
    session: AsyncSession,
    scope_type: str,
    scope_id: str | None,
    runtime_type: str,
) -> RuntimeModelDefault | None:
    normalized_scope_id = scope_id or ""
    result = await session.execute(
        select(RuntimeModelDefault).where(
            RuntimeModelDefault.scope_type == scope_type,
            RuntimeModelDefault.scope_id == normalized_scope_id,
            RuntimeModelDefault.runtime_type == runtime_type,
        )
    )
    return result.scalar_one_or_none()


async def create_runtime_model_default(
    session: AsyncSession, fields: Mapping[str, Any]
) -> RuntimeModelDefault:
    row = RuntimeModelDefault(**dict(fields))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row
