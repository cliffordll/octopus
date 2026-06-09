from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Base
from server.plugins.registry import PluginRegistryService
from server.plugins.tool_dispatcher import PluginToolDispatcher
from server.plugins.worker_manager import PluginWorkerManager


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, params))
        if method == "executeTool":
            return {
                "ok": True,
                "content": f"echo:{params['parameters']['message']}",
            }
        if method == "validateConfig":
            return {"valid": True}
        if method == "handleWebhook":
            return {"received": params["endpointKey"]}
        return {"method": method, "params": params}


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


def _manifest() -> dict[str, Any]:
    return {
        "id": "kitchen-sink",
        "apiVersion": 1,
        "version": "0.1.0",
        "displayName": "Kitchen Sink",
        "capabilities": [
            "agent.tools.register",
            "plugin.state.read",
            "plugin.state.write",
            "webhooks.receive",
        ],
        "entrypoints": {"worker": "./dist/worker.js"},
        "tools": [
            {
                "name": "echo",
                "displayName": "Echo",
                "description": "Echo a message.",
                "parametersSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            }
        ],
        "webhooks": [{"endpointKey": "demo", "displayName": "Demo"}],
    }


async def _install_ready_plugin(
    session_factory: async_sessionmaker,
) -> tuple[str, PluginRegistryService]:
    async with session_factory() as session:
        registry = PluginRegistryService(session)
        plugin = await registry.install_plugin(
            manifest=_manifest(),
            source_type="bundled",
            source_locator="packages/plugins/examples/plugin-kitchen-sink-example",
        )
        await registry.enable_plugin(plugin["id"])
        await session.commit()
        return plugin["id"], registry


async def test_step29_worker_manager_calls_registered_worker() -> None:
    manager = PluginWorkerManager()
    worker = FakeWorker()
    manager.register_worker("plugin-1", worker)

    result = await manager.call("plugin-1", "validateConfig", {"config": {}})

    assert result == {"valid": True}
    assert worker.calls == [("validateConfig", {"config": {}})]


async def test_step29_worker_manager_rejects_missing_worker() -> None:
    manager = PluginWorkerManager()

    with pytest.raises(LookupError, match="Plugin worker is not running"):
        await manager.call("plugin-1", "validateConfig", {"config": {}})


async def test_step29_tool_dispatcher_discovers_and_executes_tools(
    session_factory: async_sessionmaker,
) -> None:
    plugin_id, _ = await _install_ready_plugin(session_factory)
    worker = FakeWorker()
    manager = PluginWorkerManager()
    manager.register_worker(plugin_id, worker)

    async with session_factory() as session:
        registry = PluginRegistryService(session)
        dispatcher = PluginToolDispatcher(registry, manager)
        tools = await dispatcher.discover_tools()
        result = await dispatcher.execute_tool(
            plugin_id,
            "echo",
            {"message": "hello"},
            context={"runId": "run-1", "orgId": "org-1"},
        )

    assert tools == [
        {
            "pluginId": plugin_id,
            "pluginKey": "kitchen-sink",
            "name": "echo",
            "displayName": "Echo",
            "description": "Echo a message.",
            "parametersSchema": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        }
    ]
    assert result == {"ok": True, "content": "echo:hello"}
    assert worker.calls == [
        (
            "executeTool",
            {
                "toolName": "echo",
                "parameters": {"message": "hello"},
                "context": {"runId": "run-1", "orgId": "org-1"},
            },
        )
    ]


async def test_step29_tool_dispatcher_rejects_disabled_plugins(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        registry = PluginRegistryService(session)
        plugin = await registry.install_plugin(
            manifest=_manifest(),
            source_type="bundled",
            source_locator="packages/plugins/examples/plugin-kitchen-sink-example",
        )
        manager = PluginWorkerManager()
        dispatcher = PluginToolDispatcher(registry, manager)

        with pytest.raises(ValueError, match="Plugin is not ready"):
            await dispatcher.execute_tool(plugin["id"], "echo", {}, context={})
