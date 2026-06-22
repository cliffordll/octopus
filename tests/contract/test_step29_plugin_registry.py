from __future__ import annotations

import asyncio
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
from server.plugins.registry import PluginRegistryService
from server.plugins.worker_manager import PluginWorkerManager


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
        "capabilities": ["issues.read", "jobs.schedule", "webhooks.receive"],
        "entrypoints": {"worker": "./dist/worker.js"},
        "jobs": [
            {
                "jobKey": "sync",
                "displayName": "Sync",
                "schedule": "*/15 * * * *",
            }
        ],
        "webhooks": [
            {
                "endpointKey": "issue",
                "displayName": "Issue",
            }
        ],
    }


def _ui_manifest(plugin_id: str = "linear.connector") -> dict[str, Any]:
    return {
        **_manifest(plugin_id),
        "capabilities": [
            "issues.read",
            "jobs.schedule",
            "webhooks.receive",
            "ui.page.register",
            "ui.detailTab.register",
            "ui.dashboardWidget.register",
        ],
        "entrypoints": {
            "worker": "./dist/worker.js",
            "ui": "./dist/ui",
        },
        "ui": {
            "slots": [
                {
                    "type": "page",
                    "id": "linear-page",
                    "displayName": "Linear",
                    "exportName": "LinearPage",
                    "routePath": "linear",
                    "order": 10,
                },
                {
                    "type": "detailTab",
                    "id": "linear-issue-tab",
                    "displayName": "Linear",
                    "exportName": "LinearIssueTab",
                    "entityTypes": ["issue"],
                },
                {
                    "type": "dashboardWidget",
                    "id": "linear-widget",
                    "displayName": "Linear",
                    "exportName": "LinearWidget",
                },
            ]
        },
    }


def _git_manifest() -> dict[str, Any]:
    return {
        "id": "git.local",
        "apiVersion": 1,
        "version": "0.1.0",
        "displayName": "Git",
        "description": "Local Git workflow tools scoped to the runtime workspace cwd.",
        "author": "Octopus",
        "categories": ["workspace", "git"],
        "capabilities": ["agent.tools.register", "project.workspaces.read"],
        "entrypoints": {"worker": "./dist/worker.js"},
        "tools": [
            {
                "name": "git.status",
                "displayName": "Git Status",
                "description": "Show branch and dirty-file status.",
                "parametersSchema": {"type": "object", "properties": {}},
            }
        ],
    }


class FakeBridgeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, params))
        if method == "activate":
            return {"activated": True}
        if method == "deactivate":
            return {"deactivated": True}
        if method == "validateConfig":
            return {"valid": True}
        if method == "getData":
            return {"items": [{"id": "LIN-1"}], "key": params["key"]}
        if method == "performAction":
            return {"ok": True, "action": params["key"]}
        if method == "handleWebhook":
            return {"handled": params["endpointKey"]}
        if method == "runJob":
            return {"ran": params["jobKey"]}
        return {"method": method}


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


async def test_step29_plugin_lifecycle_routes_activate_and_deactivate_worker(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, _ = app
    worker = FakeBridgeWorker()
    worker_manager = PluginWorkerManager()
    application.state.plugin_worker_manager = worker_manager
    application.state.plugin_worker_factory = lambda plugin_id: worker
    install_code, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": _manifest(),
            "sourceType": "bundled",
            "sourceLocator": "server/plugins/bundled/plugin-linear",
        },
    )

    enable_code, enabled = await _request(
        application, "POST", f"/api/plugins/{installed['id']}/enable"
    )
    disable_code, disabled = await _request(
        application, "POST", f"/api/plugins/{installed['id']}/disable"
    )

    assert install_code == 201
    assert enable_code == 200
    assert enabled["status"] == "ready"
    assert worker_manager.is_running(installed["id"]) is False
    assert disable_code == 200
    assert disabled["status"] == "disabled"
    assert [call[0] for call in worker.calls] == ["activate", "deactivate"]


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


async def test_step29_plugin_detail_config_health_and_dashboard_routes(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, _ = app
    worker = FakeBridgeWorker()
    worker_manager = PluginWorkerManager()
    application.state.plugin_worker_manager = worker_manager
    _, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": {
                **_manifest(),
                "instanceConfigSchema": {
                    "type": "object",
                    "required": ["apiTokenSecretRef"],
                },
            },
            "sourceType": "bundled",
            "sourceLocator": "server/plugins/bundled/plugin-linear",
        },
    )

    detail_code, detail = await _request(
        application, "GET", f"/api/plugins/{installed['id']}"
    )
    config_code, config = await _request(
        application, "GET", f"/api/plugins/{installed['id']}/config"
    )
    invalid_config_code, invalid_config = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/config/test",
        json_body={"configJson": {}},
    )
    await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/config",
        json_body={"configJson": {"apiTokenSecretRef": "secret:linear"}},
    )
    await _request(application, "POST", f"/api/plugins/{installed['id']}/enable")
    worker_manager.register_worker(installed["id"], worker)
    valid_config_code, valid_config = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/config/test",
        json_body={"configJson": {"apiTokenSecretRef": "secret:linear"}},
    )
    health_code, health = await _request(
        application, "GET", f"/api/plugins/{installed['id']}/health"
    )
    dashboard_code, dashboard = await _request(
        application, "GET", f"/api/plugins/{installed['id']}/dashboard"
    )

    assert detail_code == 200
    assert detail["id"] == installed["id"]
    assert config_code == 200
    assert config["configJson"] == {}
    assert invalid_config_code == 200
    assert invalid_config["valid"] is False
    assert invalid_config["missing"] == ["apiTokenSecretRef"]
    assert valid_config_code == 200
    assert valid_config["valid"] is True
    assert health_code == 200
    assert health["workerRunning"] is True
    assert dashboard_code == 200
    assert dashboard["counts"]["jobs"] == 1
    assert dashboard["health"]["workerRunning"] is True


async def test_step29_builtin_git_plugin_health_does_not_require_external_worker(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, _ = app
    _, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": _git_manifest(),
            "sourceType": "bundled",
            "sourceLocator": "server/plugins/bundled/plugin-git",
        },
    )
    await _request(application, "POST", f"/api/plugins/{installed['id']}/enable")

    health_code, health = await _request(
        application, "GET", f"/api/plugins/{installed['id']}/health"
    )
    dashboard_code, dashboard = await _request(
        application, "GET", f"/api/plugins/{installed['id']}/dashboard"
    )

    assert health_code == 200
    assert health["healthy"] is True
    assert health["workerRunning"] is False
    assert health["workerMode"] == "builtin"
    assert dashboard_code == 200
    assert dashboard["health"]["workerMode"] == "builtin"


async def test_step29_plugin_tool_routes_discover_and_execute_builtin_git(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    proc = await asyncio.create_subprocess_exec(
        "git",
        "init",
        cwd=str(repo),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, (stderr or stdout).decode("utf-8", errors="replace")
    application, _ = app
    _, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": _git_manifest(),
            "sourceType": "bundled",
            "sourceLocator": "server/plugins/bundled/plugin-git",
        },
    )
    await _request(application, "POST", f"/api/plugins/{installed['id']}/enable")

    tools_code, tools = await _request(application, "GET", "/api/plugins/tools")
    execute_code, result = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/tools/git.status/execute",
        json_body={"context": {"workspace": {"rudderWorkspace": {"cwd": str(repo)}}}},
    )

    assert tools_code == 200
    assert tools["items"][0]["name"] == "git.status"
    assert execute_code == 200
    assert result["ok"] is True
    assert result["cwd"] == str(repo.resolve())


async def test_step29_plugin_registry_jobs_logs_and_webhook_delivery(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        service = PluginRegistryService(session)
        plugin = await service.install_plugin(
            manifest=_manifest(),
            source_type="bundled",
            source_locator="packages/plugins/examples/plugin-linear",
        )

        jobs = await service.list_jobs(plugin["id"])
        run = await service.record_job_run(
            plugin["id"],
            jobs[0]["id"],
            status="succeeded",
            output_json={"imported": 2},
        )
        delivery = await service.record_webhook_delivery(
            plugin["id"],
            endpoint_key="issue",
            request_json={"issueId": "LIN-1"},
            status="succeeded",
            response_json={"ok": True},
        )
        log = await service.add_log(
            plugin["id"],
            level="info",
            message="Imported issues",
            details_json={"count": 2},
        )
        await session.commit()

    assert jobs[0]["jobKey"] == "sync"
    assert jobs[0]["displayName"] == "Sync"
    assert run["status"] == "succeeded"
    assert run["outputJson"] == {"imported": 2}
    assert delivery["webhookKey"] == "issue"
    assert delivery["requestJson"] == {"issueId": "LIN-1"}
    assert log["message"] == "Imported issues"
    assert log["detailsJson"] == {"count": 2}


async def test_step29_plugin_jobs_logs_webhook_and_state_routes(
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
    await _request(application, "POST", f"/api/plugins/{installed['id']}/enable")

    jobs_code, jobs = await _request(
        application, "GET", f"/api/plugins/{installed['id']}/jobs"
    )
    trigger_code, run = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/jobs/{jobs[0]['id']}/trigger",
    )
    state_code, state = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/state/cursor",
        json_body={"valueJson": {"page": 2}},
    )
    webhook_code, delivery = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/webhooks/issue",
        json_body={"issueId": "LIN-1"},
    )
    logs_code, logs = await _request(
        application, "GET", f"/api/plugins/{installed['id']}/logs"
    )

    assert jobs_code == 200
    assert jobs[0]["jobKey"] == "sync"
    assert trigger_code == 200
    assert run["status"] == "queued"
    assert state_code == 200
    assert state["valueJson"] == {"page": 2}
    assert webhook_code == 200
    assert delivery["status"] == "received"
    assert logs_code == 200
    assert logs[0]["message"] == "Webhook received"


async def test_step29_plugin_webhook_route_validates_and_forwards_to_worker(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, _ = app
    worker_manager = PluginWorkerManager()
    application.state.plugin_worker_manager = worker_manager
    _, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": _manifest(),
            "sourceType": "bundled",
            "sourceLocator": "server/plugins/bundled/plugin-linear",
        },
    )
    disabled_code, disabled_delivery = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/webhooks/issue",
        json_body={"issueId": "LIN-1"},
    )
    await _request(application, "POST", f"/api/plugins/{installed['id']}/enable")
    missing_code, missing_delivery = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/webhooks/missing",
        json_body={"issueId": "LIN-1"},
    )
    worker = FakeBridgeWorker()
    worker_manager.register_worker(installed["id"], worker)
    forwarded_code, forwarded_delivery = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/webhooks/issue",
        json_body={"issueId": "LIN-1"},
    )

    assert disabled_code == 409
    assert disabled_delivery["detail"] == "Plugin is not ready"
    assert missing_code == 404
    assert missing_delivery["detail"] == "Plugin webhook endpoint not found"
    assert forwarded_code == 200
    assert forwarded_delivery["status"] == "succeeded"
    assert forwarded_delivery["responseJson"] == {"handled": "issue"}
    assert worker.calls[-1][0] == "handleWebhook"


async def test_step29_plugin_job_trigger_validates_and_forwards_to_worker(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, _ = app
    worker_manager = PluginWorkerManager()
    application.state.plugin_worker_manager = worker_manager
    _, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": _manifest(),
            "sourceType": "bundled",
            "sourceLocator": "server/plugins/bundled/plugin-linear",
        },
    )
    jobs_code, jobs = await _request(
        application, "GET", f"/api/plugins/{installed['id']}/jobs"
    )
    disabled_code, disabled_run = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/jobs/{jobs[0]['id']}/trigger",
    )
    await _request(application, "POST", f"/api/plugins/{installed['id']}/enable")
    worker = FakeBridgeWorker()
    worker_manager.register_worker(installed["id"], worker)
    forwarded_code, forwarded_run = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/jobs/{jobs[0]['id']}/trigger",
        json_body={"context": {"manual": True}},
    )

    assert jobs_code == 200
    assert disabled_code == 409
    assert disabled_run["detail"] == "Plugin is not ready"
    assert forwarded_code == 200
    assert forwarded_run["status"] == "succeeded"
    assert forwarded_run["outputJson"] == {"ran": "sync"}
    assert worker.calls[-1] == (
        "runJob",
        {
            "jobId": jobs[0]["id"],
            "jobKey": "sync",
            "context": {"manual": True},
        },
    )


async def test_step29_plugin_ui_bridge_contributions_and_worker_routes(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, _ = app
    worker_manager = PluginWorkerManager()
    application.state.plugin_worker_manager = worker_manager
    _, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": _ui_manifest(),
            "sourceType": "bundled",
            "sourceLocator": "packages/plugins/examples/plugin-linear",
        },
    )
    await _request(application, "POST", f"/api/plugins/{installed['id']}/enable")
    worker = FakeBridgeWorker()
    worker_manager.register_worker(installed["id"], worker)

    contributions_code, contributions = await _request(
        application,
        "GET",
        "/api/plugins/ui/contributions?slotType=detailTab&entityType=issue",
    )
    data_code, data = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/data/issues",
        json_body={"context": {"projectId": "project-1"}},
    )
    action_code, action = await _request(
        application,
        "POST",
        f"/api/plugins/{installed['id']}/actions/import",
        json_body={
            "input": {"issueId": "LIN-1"},
            "context": {"projectId": "project-1"},
        },
    )

    assert contributions_code == 200
    assert [slot["id"] for slot in contributions["items"]] == ["linear-issue-tab"]
    assert contributions["items"][0]["pluginId"] == installed["id"]
    assert contributions["items"][0]["assetBaseUrl"].endswith(
        f"/api/plugins/{installed['id']}/static/"
    )
    assert data_code == 200
    assert data["result"] == {"items": [{"id": "LIN-1"}], "key": "issues"}
    assert action_code == 200
    assert action["result"] == {"ok": True, "action": "import"}
    assert worker.calls[0] == (
        "getData",
        {"key": "issues", "context": {"projectId": "project-1"}},
    )


async def test_step29_plugin_ui_stream_and_static_routes(
    tmp_path,
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, _ = app
    plugin_dir = tmp_path / "linear"
    ui_dir = plugin_dir / "dist" / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "plugin.js").write_text(
        "export const marker = 'linear';", encoding="utf-8"
    )
    _, installed = await _request(
        application,
        "POST",
        "/api/plugins/install",
        json_body={
            "manifest": _ui_manifest(),
            "sourceType": "local",
            "sourceLocator": str(plugin_dir),
        },
    )
    await _request(application, "POST", f"/api/plugins/{installed['id']}/enable")

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        static_response = await client.get(
            f"/api/plugins/{installed['id']}/static/plugin.js"
        )
        stream_response = await client.get(f"/api/plugins/{installed['id']}/stream")

    assert static_response.status_code == 200
    assert "marker = 'linear'" in static_response.text
    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    assert '"pluginId":"' in stream_response.text
