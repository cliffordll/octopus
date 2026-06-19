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
from packages.database.queries.runtime_providers import get_llm_runtime_default
from packages.database.schema import (
    Agent,
    Base,
    LlmModel,
    LlmProvider,
    LlmProviderBinding,
    Organization,
)
from packages.runtimes.types import RuntimeExecutionContext, RuntimeExecutionResult
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


def test_llm_provider_model_contract_exposes_paths() -> None:
    module_name = "packages.shared.api_paths.llm"

    assert importlib.util.find_spec(module_name) is not None
    paths = importlib.import_module(module_name)

    assert paths.LLM_PROVIDER_LIST_PATH == "/api/llm/providers"
    assert paths.LLM_PROVIDER_DETAIL_PATH == "/api/llm/providers/{providerId}"
    assert paths.LLM_MODEL_LIST_PATH == "/api/llm/providers/{providerId}/models"
    assert (
        paths.LLM_MODEL_DETAIL_PATH
        == "/api/llm/providers/{providerId}/models/{modelId:path}"
    )


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


async def _seed_org(factory: async_sessionmaker, *, key: str = "runtime-models") -> str:
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=key,
                name=f"Runtime Models {key}",
                issue_prefix=org_id[:6].upper(),
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


async def test_global_provider_and_model_are_visible_across_organizations(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    source_org_id = await _seed_org(factory, key="source-runtime-models")
    target_org_id = await _seed_org(factory, key="target-runtime-models")

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{source_org_id}/runtime-providers",
        json_body={
            "runtimeType": "opencode_local",
            "providerId": "deepseek",
            "name": "DeepSeek",
            "protocol": "openai_chat_completions",
            "baseUrl": "https://deepseek.example/v1",
            "apiKey": "sk-global",
        },
    )
    assert create_code == 201
    assert created["scope"] == "instance"
    assert created["orgId"] is None

    model_code, model = await _request(
        application,
        "POST",
        f"/api/orgs/{source_org_id}/runtime-providers/deepseek/models",
        params={"runtimeType": "opencode_local"},
        json_body={
            "modelId": "deepseek-v4-flash",
            "displayName": "DeepSeek V4 Flash",
        },
    )
    assert model_code == 201
    assert model["scope"] == "instance"

    providers_code, providers = await _request(
        application,
        "GET",
        f"/api/orgs/{target_org_id}/runtime-providers",
        params={"runtimeType": "opencode_local"},
    )
    assert providers_code == 200
    assert [(provider["scope"], provider["providerId"]) for provider in providers] == [
        ("instance", "deepseek")
    ]

    models_code, models = await _request(
        application,
        "GET",
        f"/api/orgs/{target_org_id}/runtime-providers/deepseek/models",
        params={"runtimeType": "opencode_local"},
    )
    assert models_code == 200
    assert [(item["scope"], item["modelId"]) for item in models] == [
        ("instance", "deepseek-v4-flash")
    ]


async def test_llm_provider_and_model_are_visible_across_runtime_switches(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory, key="runtime-switch-provider-models")

    create_code, created = await _request(
        application,
        "POST",
        "/api/llm/providers",
        json_body={
            "providerId": "deepseek",
            "name": "DeepSeek",
            "protocol": "openai_chat_completions",
            "baseUrl": "https://deepseek.example/v1",
            "apiKey": "sk-instance",
        },
    )
    assert create_code == 201
    assert created["providerId"] == "deepseek"
    assert created["apiKey"] == "***REDACTED***"
    assert created["hasApiKey"] is True

    model_code, model = await _request(
        application,
        "POST",
        "/api/llm/providers/deepseek/models",
        json_body={
            "modelId": "deepseek-v4-flash",
            "displayName": "DeepSeek V4 Flash",
        },
    )
    assert model_code == 201
    assert model["providerId"] == "deepseek"

    for runtime_type in ["opencode_local", "codex_local", "claude_local"]:
        providers_code, providers = await _request(
            application,
            "GET",
            f"/api/orgs/{org_id}/runtime-providers",
            params={"runtimeType": runtime_type},
        )
        assert providers_code == 200
        assert [
            (provider["scope"], provider["providerId"]) for provider in providers
        ] == [("instance", "deepseek")]

        models_code, models = await _request(
            application,
            "GET",
            f"/api/orgs/{org_id}/runtime-providers/deepseek/models",
            params={"runtimeType": runtime_type},
        )
        assert models_code == 200
        assert [(item["scope"], item["modelId"]) for item in models] == [
            ("instance", "deepseek-v4-flash")
        ]


async def test_llm_model_route_uses_runtime_type_query_for_default_model(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app

    create_code, _ = await _request(
        application,
        "POST",
        "/api/llm/providers",
        json_body={
            "runtimeType": "openclaw_local",
            "providerId": "deepseek",
            "name": "DeepSeek",
            "protocol": "openai_chat_completions",
        },
    )
    assert create_code == 201

    model_code, model = await _request(
        application,
        "POST",
        "/api/llm/providers/deepseek/models",
        params={"runtimeType": "openclaw_local"},
        json_body={
            "modelId": "deepseek-v4-flash",
            "displayName": "DeepSeek V4 Flash",
        },
    )
    assert model_code == 201
    assert model["providerId"] == "deepseek"

    async with factory() as session:
        openclaw_default = await get_llm_runtime_default(
            session, "instance", "", "openclaw_local"
        )
        opencode_default = await get_llm_runtime_default(
            session, "instance", "", "opencode_local"
        )

    assert openclaw_default is not None
    assert openclaw_default.provider_id == "deepseek"
    assert openclaw_default.model_id == "deepseek-v4-flash"
    assert opencode_default is None


async def test_llm_provider_and_model_are_instance_scoped_across_organizations(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    source_org_id = await _seed_org(factory, key="private-source-runtime-models")
    target_org_id = await _seed_org(factory, key="private-target-runtime-models")

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{source_org_id}/runtime-providers",
        json_body={
            "runtimeType": "opencode_local",
            "providerId": "private",
            "name": "Private",
            "protocol": "openai_chat_completions",
        },
    )
    assert create_code == 201
    assert created["scope"] == "instance"
    assert created["orgId"] is None

    model_code, model = await _request(
        application,
        "POST",
        f"/api/orgs/{source_org_id}/runtime-providers/private/models",
        params={"runtimeType": "opencode_local"},
        json_body={
            "modelId": "private-model",
            "displayName": "Private Model",
        },
    )
    assert model_code == 201
    assert model["scope"] == "instance"

    providers_code, providers = await _request(
        application,
        "GET",
        f"/api/orgs/{target_org_id}/runtime-providers",
        params={"runtimeType": "opencode_local"},
    )
    assert providers_code == 200
    assert [(provider["scope"], provider["providerId"]) for provider in providers] == [
        ("instance", "private")
    ]

    models_code, models = await _request(
        application,
        "GET",
        f"/api/orgs/{target_org_id}/runtime-providers/private/models",
        params={"runtimeType": "opencode_local"},
    )
    assert models_code == 200
    assert [(item["scope"], item["modelId"]) for item in models] == [
        ("instance", "private-model")
    ]


async def test_chat_runtime_config_uses_global_default_model_across_organizations(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    source_org_id = await _seed_org(factory, key="default-source-runtime-models")
    target_org_id = await _seed_org(factory, key="default-target-runtime-models")
    agent_id = str(uuid.uuid4())
    captured: dict[str, Any] = {}

    await _request(
        application,
        "POST",
        f"/api/orgs/{source_org_id}/runtime-providers",
        json_body={
            "runtimeType": "codex_local",
            "providerId": "deepseek",
            "name": "DeepSeek",
            "protocol": "openai_chat_completions",
            "baseUrl": "https://deepseek.example/v1",
            "apiKey": "sk-global-default",
        },
    )
    model_code, _ = await _request(
        application,
        "POST",
        f"/api/orgs/{source_org_id}/runtime-providers/deepseek/models",
        params={"runtimeType": "codex_local"},
        json_body={
            "modelId": "deepseek-v4-flash",
            "displayName": "DeepSeek V4 Flash",
        },
    )
    assert model_code == 201

    class CapturingAdapter:
        type = "codex_local"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            captured["config"] = context.config
            return RuntimeExecutionResult(exit_code=0, result_json={"summary": "reply"})

    async with factory() as session:
        async with session.begin():
            session.add(
                Agent(
                    id=agent_id,
                    org_id=target_org_id,
                    name="Default Model Agent",
                    role="engineer",
                    status="idle",
                    agent_runtime_type="codex_local",
                    agent_runtime_config={},
                    runtime_config={},
                )
            )

    monkeypatch.setattr(
        chat_service_module, "get_runtime_adapter", lambda _: CapturingAdapter()
    )

    chat = await _create_chat(application, target_org_id, agent_id)
    code, _ = await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json_body={"body": "use default"},
    )

    assert code == 201
    runtime_provider = captured["config"]["_octopus"]["runtimeProvider"]
    assert runtime_provider["providerId"] == "deepseek"
    assert runtime_provider["apiKey"] == "sk-global-default"
    assert runtime_provider["model"]["modelId"] == "deepseek-v4-flash"


@pytest.mark.parametrize(
    "runtime_type", ["opencode_local", "codex_local", "claude_local"]
)
async def test_chat_runtime_config_includes_database_provider_model(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
    runtime_type: str,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id = await _seed_org(factory)
    agent_id = str(uuid.uuid4())
    captured: dict[str, Any] = {}

    class CapturingAdapter:
        type = runtime_type

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            captured["config"] = context.config
            return RuntimeExecutionResult(exit_code=0, result_json={"summary": "reply"})

    async with factory() as session:
        async with session.begin():
            session.add(
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="OpenCode Agent",
                    role="engineer",
                    status="idle",
                    agent_runtime_type=runtime_type,
                    agent_runtime_config={"model": "deepseek/deepseek-v4-flash"},
                    runtime_config={},
                )
            )
            session.add(
                LlmProvider(
                    id=str(uuid.uuid4()),
                    provider_id="deepseek",
                    name="DeepSeek",
                    protocol="openai_chat_completions",
                    npm_package="@ai-sdk/openai-compatible",
                    enabled=True,
                )
            )
            session.add(
                LlmProviderBinding(
                    id=str(uuid.uuid4()),
                    scope_type="instance",
                    scope_id="",
                    provider_id="deepseek",
                    base_url="https://deepseek.example/v1",
                    api_key="sk-db",
                    config_json={"timeoutSec": 30},
                    enabled=True,
                )
            )
            session.add(
                LlmModel(
                    id=str(uuid.uuid4()),
                    provider_id="deepseek",
                    model_id="deepseek-v4-flash",
                    display_name="DeepSeek V4 Flash",
                    metadata_json={},
                    enabled=True,
                )
            )

    monkeypatch.setattr(
        chat_service_module, "get_runtime_adapter", lambda _: CapturingAdapter()
    )

    chat = await _create_chat(application, org_id, agent_id)
    code, _ = await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json_body={"body": "你好"},
    )

    assert code == 201
    runtime_provider = captured["config"]["_octopus"]["runtimeProvider"]
    assert runtime_provider == {
        "providerId": "deepseek",
        "name": "DeepSeek",
        "protocol": "openai_chat_completions",
        "npmPackage": "@ai-sdk/openai-compatible",
        "baseUrl": "https://deepseek.example/v1",
        "apiKey": "sk-db",
        "config": {"timeoutSec": 30},
        "model": {
            "modelId": "deepseek-v4-flash",
            "displayName": "DeepSeek V4 Flash",
            "metadata": {},
        },
    }


async def _create_chat(app: FastAPI, org_id: str, agent_id: str) -> dict[str, Any]:
    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json_body={"title": "Runtime provider chat", "preferredAgentId": agent_id},
    )
    assert code == 201
    return body
