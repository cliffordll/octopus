from __future__ import annotations

from collections.abc import AsyncIterator
import asyncio
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Base
from server.plugins.host_services import PluginHostServices
from server.plugins.registry import PluginRegistryService
from server.plugins.tool_dispatcher import PluginToolDispatcher
from server.plugins.worker_manager import PluginWorkerManager


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, params))
        if method == "activate":
            return {"activated": True}
        if method == "deactivate":
            return {"deactivated": True}
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


async def _run_git(cwd: Any, args: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise AssertionError(
            (stderr or stdout).decode("utf-8", errors="replace").strip()
        )


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
            },
            {
                "name": "git.branch.create",
                "displayName": "Create Branch",
                "description": "Create a local branch. Requires confirm=true.",
                "parametersSchema": {
                    "type": "object",
                    "required": ["branchName", "confirm"],
                    "properties": {
                        "branchName": {"type": "string"},
                        "confirm": {"type": "boolean", "const": True},
                    },
                },
            },
        ],
    }


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


async def test_step29_worker_manager_activate_and_deactivate_plugin() -> None:
    manager = PluginWorkerManager()
    worker = FakeWorker()

    activated = await manager.activate_plugin(
        "plugin-1",
        worker,
        manifest={"id": "demo"},
        config={"enabled": True},
    )
    deactivated = await manager.deactivate_plugin("plugin-1")

    assert activated == {"activated": True}
    assert deactivated == {"deactivated": True}
    assert manager.is_running("plugin-1") is False
    assert worker.calls == [
        (
            "activate",
            {
                "pluginId": "plugin-1",
                "manifest": {"id": "demo"},
                "config": {"enabled": True},
            },
        ),
        ("deactivate", {"pluginId": "plugin-1"}),
    ]


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


async def test_step29_builtin_git_tool_uses_runtime_workspace_cwd(
    session_factory: async_sessionmaker,
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    await _run_git(repo, ["init"])
    await _run_git(repo, ["config", "user.name", "Octopus Test"])
    await _run_git(repo, ["config", "user.email", "octopus@example.test"])
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    await _run_git(repo, ["add", "README.md"])
    await _run_git(repo, ["commit", "-m", "Initial commit"])
    (repo / "README.md").write_text("hello\nworld\n", encoding="utf-8")

    async with session_factory() as session:
        registry = PluginRegistryService(session)
        plugin = await registry.install_plugin(
            manifest=_git_manifest(),
            source_type="bundled",
            source_locator="server/plugins/bundled/plugin-git",
        )
        await registry.enable_plugin(plugin["id"])
        await session.commit()

    async with session_factory() as session:
        dispatcher = PluginToolDispatcher(
            PluginRegistryService(session),
            PluginWorkerManager(),
        )
        result = await dispatcher.execute_tool(
            plugin["id"],
            "git.status",
            {},
            context={"workspace": {"octopusWorkspace": {"cwd": str(repo)}}},
        )

    assert result["ok"] is True
    assert result["cwd"] == str(repo.resolve())
    assert "README.md" in result["stdout"]


async def test_step29_builtin_git_tool_requires_confirm_for_mutations(
    session_factory: async_sessionmaker,
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    await _run_git(repo, ["init"])

    async with session_factory() as session:
        registry = PluginRegistryService(session)
        plugin = await registry.install_plugin(
            manifest=_git_manifest(),
            source_type="bundled",
            source_locator="server/plugins/bundled/plugin-git",
        )
        await registry.enable_plugin(plugin["id"])
        await session.commit()

    async with session_factory() as session:
        dispatcher = PluginToolDispatcher(
            PluginRegistryService(session),
            PluginWorkerManager(),
        )
        with pytest.raises(
            PermissionError,
            match="Mutating git tools require 'confirm: true'",
        ):
            await dispatcher.execute_tool(
                plugin["id"],
                "git.branch.create",
                {"branchName": "demo"},
                context={"workspace": {"octopusWorkspace": {"cwd": str(repo)}}},
            )


async def test_step29_host_services_gate_state_logs_and_entities(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        registry = PluginRegistryService(session)
        plugin = await registry.install_plugin(
            manifest={
                **_manifest(),
                "capabilities": [
                    "plugin.state.read",
                    "plugin.state.write",
                    "activity.log.write",
                    "issues.read",
                ],
            },
            source_type="bundled",
            source_locator="server/plugins/bundled/plugin-kitchen-sink-example",
        )
        await registry.enable_plugin(plugin["id"])
        host = PluginHostServices(registry, plugin["id"])

        state = await host.set_state("cursor", {"page": 3})
        read_state = await host.get_state("cursor")
        log = await host.add_log(
            level="info",
            message="Mapped issue",
            details_json={"externalId": "LIN-1"},
        )
        mapping = await host.upsert_entity_mapping(
            external_type="linear.issue",
            external_id="LIN-1",
            local_type="issue",
            local_id="issue-1",
            metadata_json={"team": "core"},
        )
        mappings = await host.list_entity_mappings(local_type="issue")

    assert state["valueJson"] == {"page": 3}
    assert read_state is not None
    assert read_state["valueJson"] == {"page": 3}
    assert log["message"] == "Mapped issue"
    assert mapping["externalId"] == "LIN-1"
    assert mappings == [mapping]


async def test_step29_host_services_reject_undeclared_capabilities(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        registry = PluginRegistryService(session)
        plugin = await registry.install_plugin(
            manifest={
                **_manifest(),
                "capabilities": ["plugin.state.read"],
            },
            source_type="bundled",
            source_locator="server/plugins/bundled/plugin-kitchen-sink-example",
        )
        await registry.enable_plugin(plugin["id"])
        host = PluginHostServices(registry, plugin["id"])

        with pytest.raises(
            PermissionError,
            match="Plugin capability is not declared: plugin.state.write",
        ):
            await host.set_state("cursor", {"page": 3})

        with pytest.raises(
            PermissionError,
            match="Plugin capability is not declared: activity.log.write",
        ):
            await host.add_log(level="info", message="Denied")
