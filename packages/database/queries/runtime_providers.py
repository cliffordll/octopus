from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import LlmModel, LlmProvider, LlmProviderBinding, LlmRuntimeDefault
from ._compat import delete_returning_one, update_returning_one


async def list_llm_providers(session: AsyncSession) -> Sequence[LlmProvider]:
    result = await session.execute(
        select(LlmProvider).order_by(LlmProvider.name, LlmProvider.provider_id)
    )
    return result.scalars().all()


async def get_llm_provider(
    session: AsyncSession, provider_id: str
) -> LlmProvider | None:
    result = await session.execute(
        select(LlmProvider).where(LlmProvider.provider_id == provider_id)
    )
    return result.scalar_one_or_none()


async def create_llm_provider(
    session: AsyncSession, fields: Mapping[str, Any]
) -> LlmProvider:
    row = LlmProvider(**dict(fields))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def update_llm_provider(
    session: AsyncSession, provider_id: str, fields: Mapping[str, Any]
) -> LlmProvider | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        LlmProvider,
        LlmProvider.provider_id == provider_id,
        values,
    )


async def delete_llm_provider(
    session: AsyncSession, provider_id: str
) -> LlmProvider | None:
    return await delete_returning_one(
        session, LlmProvider, LlmProvider.provider_id == provider_id
    )


async def get_llm_provider_binding(
    session: AsyncSession, scope_type: str, scope_id: str | None, provider_id: str
) -> LlmProviderBinding | None:
    normalized_scope_id = scope_id or ""
    result = await session.execute(
        select(LlmProviderBinding).where(
            LlmProviderBinding.scope_type == scope_type,
            LlmProviderBinding.scope_id == normalized_scope_id,
            LlmProviderBinding.provider_id == provider_id,
        )
    )
    return result.scalar_one_or_none()


async def create_llm_provider_binding(
    session: AsyncSession, fields: Mapping[str, Any]
) -> LlmProviderBinding:
    row = LlmProviderBinding(**dict(fields))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def update_llm_provider_binding(
    session: AsyncSession,
    scope_type: str,
    scope_id: str | None,
    provider_id: str,
    fields: Mapping[str, Any],
) -> LlmProviderBinding | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        LlmProviderBinding,
        and_(
            LlmProviderBinding.scope_type == scope_type,
            LlmProviderBinding.scope_id == (scope_id or ""),
            LlmProviderBinding.provider_id == provider_id,
        ),
        values,
    )


async def delete_llm_provider_bindings(session: AsyncSession, provider_id: str) -> None:
    await session.execute(
        delete(LlmProviderBinding).where(LlmProviderBinding.provider_id == provider_id)
    )


async def list_llm_models(
    session: AsyncSession, provider_id: str
) -> Sequence[LlmModel]:
    result = await session.execute(
        select(LlmModel)
        .where(LlmModel.provider_id == provider_id)
        .order_by(LlmModel.display_name, LlmModel.model_id)
    )
    return result.scalars().all()


async def get_llm_model(
    session: AsyncSession, provider_id: str, model_id: str
) -> LlmModel | None:
    result = await session.execute(
        select(LlmModel).where(
            LlmModel.provider_id == provider_id,
            LlmModel.model_id == model_id,
        )
    )
    return result.scalar_one_or_none()


async def create_llm_model(
    session: AsyncSession, fields: Mapping[str, Any]
) -> LlmModel:
    row = LlmModel(**dict(fields))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def update_llm_model(
    session: AsyncSession,
    provider_id: str,
    model_id: str,
    fields: Mapping[str, Any],
) -> LlmModel | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    return await update_returning_one(
        session,
        LlmModel,
        and_(LlmModel.provider_id == provider_id, LlmModel.model_id == model_id),
        values,
    )


async def delete_llm_model(
    session: AsyncSession, provider_id: str, model_id: str
) -> LlmModel | None:
    return await delete_returning_one(
        session,
        LlmModel,
        and_(LlmModel.provider_id == provider_id, LlmModel.model_id == model_id),
    )


async def delete_llm_models_for_provider(
    session: AsyncSession, provider_id: str
) -> None:
    await session.execute(delete(LlmModel).where(LlmModel.provider_id == provider_id))


async def get_llm_runtime_default(
    session: AsyncSession,
    scope_type: str,
    scope_id: str | None,
    runtime_type: str,
) -> LlmRuntimeDefault | None:
    normalized_scope_id = scope_id or ""
    result = await session.execute(
        select(LlmRuntimeDefault).where(
            LlmRuntimeDefault.scope_type == scope_type,
            LlmRuntimeDefault.scope_id == normalized_scope_id,
            LlmRuntimeDefault.runtime_type == runtime_type,
        )
    )
    return result.scalar_one_or_none()


async def create_llm_runtime_default(
    session: AsyncSession, fields: Mapping[str, Any]
) -> LlmRuntimeDefault:
    row = LlmRuntimeDefault(**dict(fields))
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


# Compatibility wrappers for existing service/cost call sites.
async def list_runtime_providers(
    session: AsyncSession, org_id: str, runtime_type: str
) -> Sequence[LlmProvider]:
    del org_id, runtime_type
    return await list_llm_providers(session)


async def list_global_runtime_providers(
    session: AsyncSession, runtime_type: str
) -> Sequence[LlmProvider]:
    del runtime_type
    return await list_llm_providers(session)


async def get_runtime_provider(
    session: AsyncSession, org_id: str, runtime_type: str, provider_id: str
) -> LlmProvider | None:
    del org_id, runtime_type
    return await get_llm_provider(session, provider_id)


async def get_global_runtime_provider(
    session: AsyncSession, runtime_type: str, provider_id: str
) -> LlmProvider | None:
    del runtime_type
    return await get_llm_provider(session, provider_id)


async def create_runtime_provider(
    session: AsyncSession, fields: Mapping[str, Any]
) -> LlmProvider:
    provider_fields = {
        key: value
        for key, value in fields.items()
        if key in {"id", "provider_id", "name", "protocol", "npm_package", "enabled"}
    }
    return await create_llm_provider(session, provider_fields)


async def create_global_runtime_provider(
    session: AsyncSession, fields: Mapping[str, Any]
) -> LlmProvider:
    return await create_runtime_provider(session, fields)


async def update_runtime_provider(
    session: AsyncSession,
    org_id: str,
    runtime_type: str,
    provider_id: str,
    fields: Mapping[str, Any],
) -> LlmProvider | None:
    del org_id, runtime_type
    return await update_llm_provider(session, provider_id, fields)


async def update_global_runtime_provider(
    session: AsyncSession,
    runtime_type: str,
    provider_id: str,
    fields: Mapping[str, Any],
) -> LlmProvider | None:
    del runtime_type
    return await update_llm_provider(session, provider_id, fields)


async def delete_runtime_provider(
    session: AsyncSession, org_id: str, runtime_type: str, provider_id: str
) -> LlmProvider | None:
    del org_id, runtime_type
    return await delete_llm_provider(session, provider_id)


async def delete_global_runtime_provider(
    session: AsyncSession, runtime_type: str, provider_id: str
) -> LlmProvider | None:
    del runtime_type
    return await delete_llm_provider(session, provider_id)


async def delete_runtime_models_for_provider(
    session: AsyncSession, org_id: str, runtime_type: str, provider_id: str
) -> None:
    del org_id, runtime_type
    await delete_llm_models_for_provider(session, provider_id)


async def delete_global_runtime_models_for_provider(
    session: AsyncSession, runtime_type: str, provider_id: str
) -> None:
    del runtime_type
    await delete_llm_models_for_provider(session, provider_id)


async def list_runtime_models(
    session: AsyncSession, org_id: str, runtime_type: str, provider_id: str
) -> Sequence[LlmModel]:
    del org_id, runtime_type
    return await list_llm_models(session, provider_id)


async def list_global_runtime_models(
    session: AsyncSession, runtime_type: str, provider_id: str
) -> Sequence[LlmModel]:
    del runtime_type
    return await list_llm_models(session, provider_id)


async def get_runtime_model(
    session: AsyncSession,
    org_id: str,
    runtime_type: str,
    provider_id: str,
    model_id: str,
) -> LlmModel | None:
    del org_id, runtime_type
    return await get_llm_model(session, provider_id, model_id)


async def get_global_runtime_model(
    session: AsyncSession,
    runtime_type: str,
    provider_id: str,
    model_id: str,
) -> LlmModel | None:
    del runtime_type
    return await get_llm_model(session, provider_id, model_id)


async def create_runtime_model(
    session: AsyncSession, fields: Mapping[str, Any]
) -> LlmModel:
    model_fields = {
        key: value
        for key, value in fields.items()
        if key
        in {"id", "provider_id", "model_id", "display_name", "metadata_json", "enabled"}
    }
    return await create_llm_model(session, model_fields)


async def create_global_runtime_model(
    session: AsyncSession, fields: Mapping[str, Any]
) -> LlmModel:
    return await create_runtime_model(session, fields)


async def update_runtime_model(
    session: AsyncSession,
    org_id: str,
    runtime_type: str,
    provider_id: str,
    model_id: str,
    fields: Mapping[str, Any],
) -> LlmModel | None:
    del org_id, runtime_type
    return await update_llm_model(session, provider_id, model_id, fields)


async def update_global_runtime_model(
    session: AsyncSession,
    runtime_type: str,
    provider_id: str,
    model_id: str,
    fields: Mapping[str, Any],
) -> LlmModel | None:
    del runtime_type
    return await update_llm_model(session, provider_id, model_id, fields)


async def delete_runtime_model(
    session: AsyncSession,
    org_id: str,
    runtime_type: str,
    provider_id: str,
    model_id: str,
) -> LlmModel | None:
    del org_id, runtime_type
    return await delete_llm_model(session, provider_id, model_id)


async def delete_global_runtime_model(
    session: AsyncSession,
    runtime_type: str,
    provider_id: str,
    model_id: str,
) -> LlmModel | None:
    del runtime_type
    return await delete_llm_model(session, provider_id, model_id)


async def get_runtime_model_default(
    session: AsyncSession,
    scope_type: str,
    scope_id: str | None,
    runtime_type: str,
) -> LlmRuntimeDefault | None:
    return await get_llm_runtime_default(session, scope_type, scope_id, runtime_type)


async def create_runtime_model_default(
    session: AsyncSession, fields: Mapping[str, Any]
) -> LlmRuntimeDefault:
    return await create_llm_runtime_default(session, fields)
