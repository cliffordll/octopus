from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import (
    Base,
    Plugin,
    PluginConfig,
    PluginEntity,
    PluginJob,
    PluginJobRun,
    PluginLog,
    PluginOrganizationSetting,
    PluginState,
    PluginWebhookDelivery,
)
from server.app import create_app
from server.services.plugin_registry import PluginRegistryService


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker]:
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def app() -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
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
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body)
    return response.status_code, response.json()


def _manifest(plugin_id: str = "linear.connector") -> dict[str, Any]:
    return {
        "id": plugin_id,
        "apiVersion": 1,
        "version": "0.1.0",
        "displayName": "Linear",
        "capabilities": ["issues.read"],
        "entrypoints": {"worker": "./dist/worker.js"},
    }


def test_step29_plugin_schema_matches_expected_tables_and_columns() -> None:
    assert Plugin.__tablename__ == "plugins"
    assert PluginConfig.__tablename__ == "plugin_config"
    assert PluginState.__tablename__ == "plugin_state"
    assert PluginEntity.__tablename__ == "plugin_entities"
    assert PluginJob.__tablename__ == "plugin_jobs"
    assert PluginJobRun.__tablename__ == "plugin_job_runs"
    assert PluginLog.__tablename__ == "plugin_logs"
    assert PluginWebhookDelivery.__tablename__ == "plugin_webhook_deliveries"
    assert PluginOrganizationSetting.__tablename__ == "plugin_organization_settings"

    plugin_columns = set(inspect(Plugin).columns.keys())
    assert {
        "id",
        "plugin_key",
        "display_name",
        "version",
        "status",
        "source_type",
        "source_locator",
        "manifest_json",
        "installed_at",
        "enabled_at",
        "disabled_at",
        "uninstalled_at",
        "created_at",
        "updated_at",
    } <= plugin_columns


async def test_step29_plugin_registry_installs_and_lists_plugins(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        service = PluginRegistryService(session)

        installed = await service.install_plugin(
            manifest=_manifest(),
            source_type="bundled",
            source_locator="packages/plugins/examples/plugin-linear",
        )
        await session.commit()

        plugins = await service.list_plugins()

    assert installed["pluginKey"] == "linear.connector"
    assert installed["status"] == "installed"
    assert installed["manifest"]["id"] == "linear.connector"
    assert len(plugins) == 1
    assert plugins[0]["id"] == installed["id"]
    assert plugins[0]["pluginKey"] == "linear.connector"
    assert plugins[0]["status"] == "installed"


async def test_step29_plugin_lifecycle_enable_disable_uninstall(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        service = PluginRegistryService(session)
        plugin = await service.install_plugin(
            manifest=_manifest(),
            source_type="bundled",
            source_locator="packages/plugins/examples/plugin-linear",
        )

        ready = await service.enable_plugin(plugin["id"])
        disabled = await service.disable_plugin(plugin["id"], reason="maintenance")
        uninstalled = await service.uninstall_plugin(plugin["id"])
        await session.commit()

    assert ready["status"] == "ready"
    assert ready["enabledAt"] is not None
    assert disabled["status"] == "disabled"
    assert disabled["disabledAt"] is not None
    assert uninstalled["status"] == "uninstalled"
    assert uninstalled["uninstalledAt"] is not None


async def test_step29_plugin_registry_upserts_config_and_state(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        service = PluginRegistryService(session)
        plugin = await service.install_plugin(
            manifest=_manifest(),
            source_type="bundled",
            source_locator="packages/plugins/examples/plugin-linear",
        )

        config = await service.upsert_config(
            plugin["id"], {"apiTokenSecretRef": "secret:linear"}
        )
        state = await service.set_state(plugin["id"], "cursor", {"page": 2})
        await session.commit()

    assert config["configJson"] == {"apiTokenSecretRef": "secret:linear"}
    assert state["key"] == "cursor"
    assert state["valueJson"] == {"page": 2}


async def test_step29_plugin_management_routes_install_and_lifecycle(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, _ = app

    install_code, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": _manifest(),
            "sourceType": "bundled",
            "sourceLocator": "packages/plugins/examples/plugin-linear",
        },
    )
    enable_code, enabled = await _request(
        application, "POST", f"/api/plugins/{installed['id']}/enable"
    )
    disable_code, disabled = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/disable",
        json_body={"reason": "maintenance"},
    )
    uninstall_code, uninstalled = await _request(
        application, "DELETE", f"/api/plugins/{installed['id']}"
    )

    assert install_code == 201
    assert installed["pluginKey"] == "linear.connector"
    assert enable_code == 200
    assert enabled["status"] == "ready"
    assert disable_code == 200
    assert disabled["status"] == "disabled"
    assert uninstall_code == 200
    assert uninstalled["status"] == "uninstalled"


async def test_step29_plugin_management_routes_save_config(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, _ = app
    _, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": _manifest(),
            "sourceType": "bundled",
            "sourceLocator": "packages/plugins/examples/plugin-linear",
        },
    )

    status_code, config = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/config",
        json_body={"configJson": {"apiTokenSecretRef": "secret:linear"}},
    )

    assert status_code == 200
    assert config["pluginId"] == installed["id"]
    assert config["configJson"] == {"apiTokenSecretRef": "secret:linear"}
