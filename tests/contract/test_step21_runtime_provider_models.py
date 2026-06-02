from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
import importlib
import importlib.util
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Base, Organization
from server.app import create_app


def test_runtime_provider_model_contract_exposes_paths() -> None:
    module_name = "packages.shared.api_paths.runtime_providers"

    assert importlib.util.find_spec(module_name) is not None
    paths = importlib.import_module(module_name)

    assert paths.ORG_RUNTIME_PROVIDER_LIST_PATH == "/api/orgs/{orgId}/runtime-providers"
    assert (
        paths.ORG_RUNTIME_PROVIDER_DETAIL_PATH
        == "/api/orgs/{orgId}/runtime-providers/{providerId}"
    )
    assert (
        paths.ORG_RUNTIME_MODEL_LIST_PATH
        == "/api/orgs/{orgId}/runtime-providers/{providerId}/models"
    )
    assert (
        paths.ORG_RUNTIME_MODEL_DETAIL_PATH
        == "/api/orgs/{orgId}/runtime-providers/{providerId}/models/{modelId:path}"
    )
    assert not hasattr(paths, "ORG_RUNTIME_MODEL_REFRESH_PATH")


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    try:
        yield application, factory
    finally:
        await engine.dispose()


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body, params=params)
    if response.content:
        return response.status_code, response.json()
    return response.status_code, None


async def _seed_org(factory: async_sessionmaker) -> str:
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key="runtime-models",
                name="Runtime Models",
                issue_prefix="RTM",
            )
        )
        await session.commit()
    return org_id


async def test_provider_crud_redacts_api_key(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/runtime-providers",
        json_body={
            "runtimeType": "opencode_local",
            "providerId": "kimi",
            "name": "Kimi",
            "protocol": "openai_chat_completions",
            "baseUrl": "https://api.moonshot.cn/v1",
            "apiKey": "sk-secret",
            "config": {"timeoutSec": 60},
        },
    )

    assert create_code == 201
    assert created["providerId"] == "kimi"
    assert created["apiKey"] == "***REDACTED***"
    assert created["hasApiKey"] is True
    assert created["config"] == {"timeoutSec": 60}

    list_code, providers = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/runtime-providers",
        params={"runtimeType": "opencode_local"},
    )

    assert list_code == 200
    assert providers[0]["apiKey"] == "***REDACTED***"
    assert providers[0]["hasApiKey"] is True

    patch_code, patched = await _request(
        application,
        "PATCH",
        f"/api/orgs/{org_id}/runtime-providers/kimi",
        params={"runtimeType": "opencode_local"},
        json_body={
            "name": "Kimi OpenAI",
            "apiKey": "***REDACTED***",
            "enabled": False,
        },
    )

    assert patch_code == 200
    assert patched["name"] == "Kimi OpenAI"
    assert patched["apiKey"] == "***REDACTED***"
    assert patched["hasApiKey"] is True
    assert patched["enabled"] is False

    delete_code, deleted = await _request(
        application,
        "DELETE",
        f"/api/orgs/{org_id}/runtime-providers/kimi",
        params={"runtimeType": "opencode_local"},
    )

    assert delete_code == 200
    assert deleted["providerId"] == "kimi"


async def test_model_crud_is_database_only(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)

    await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/runtime-providers",
        json_body={
            "runtimeType": "opencode_local",
            "providerId": "kimi",
            "name": "Kimi",
            "protocol": "openai_chat_completions",
        },
    )

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/runtime-providers/kimi/models",
        params={"runtimeType": "opencode_local"},
        json_body={
            "modelId": "kimik/kimi-k2.5",
            "displayName": "Kimi K2.5",
            "metadata": {"contextWindow": 128000},
        },
    )

    assert create_code == 201
    assert created["providerId"] == "kimi"
    assert created["modelId"] == "kimik/kimi-k2.5"
    assert created["metadata"] == {"contextWindow": 128000}

    list_code, models = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/runtime-providers/kimi/models",
        params={"runtimeType": "opencode_local"},
    )

    assert list_code == 200
    assert [model["modelId"] for model in models] == ["kimik/kimi-k2.5"]

    refresh_code, _ = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/runtime-providers/kimi/models/refresh",
        params={"runtimeType": "opencode_local"},
    )

    assert refresh_code in {404, 405}

    patch_code, patched = await _request(
        application,
        "PATCH",
        f"/api/orgs/{org_id}/runtime-providers/kimi/models/kimik/kimi-k2.5",
        params={"runtimeType": "opencode_local"},
        json_body={"displayName": "Kimi K2.5 Chat", "enabled": False},
    )

    assert patch_code == 200
    assert patched["displayName"] == "Kimi K2.5 Chat"
    assert patched["enabled"] is False

    delete_code, deleted = await _request(
        application,
        "DELETE",
        f"/api/orgs/{org_id}/runtime-providers/kimi/models/kimik/kimi-k2.5",
        params={"runtimeType": "opencode_local"},
    )

    assert delete_code == 200
    assert deleted["modelId"] == "kimik/kimi-k2.5"
