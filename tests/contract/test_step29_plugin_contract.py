from __future__ import annotations

import json
from typing import Any

from httpx import ASGITransport, AsyncClient

from packages.shared.api_paths.plugins import (
    PLUGIN_AVAILABLE_PATH,
    PLUGIN_CONFIG_PATH,
    PLUGIN_DETAIL_PATH,
    PLUGIN_EXAMPLES_PATH,
    PLUGIN_LIST_PATH,
    PLUGIN_STATIC_PATH,
    PLUGIN_TOOL_EXECUTE_PATH,
    PLUGIN_TOOLS_PATH,
    PLUGIN_UI_CONTRIBUTIONS_PATH,
    PLUGIN_UI_STREAM_PATH,
)
from packages.shared.constants.plugins import (
    PLUGIN_CAPABILITIES,
    PLUGIN_STATUSES,
    PLUGIN_UI_SLOT_TYPES,
)
from packages.shared.validators.plugins import validate_plugin_manifest
from server.app import create_app
from server.plugins.catalog import DEFAULT_PLUGIN_CATALOG_ROOT, load_plugin_catalog


def _manifest(plugin_id: str = "linear.connector") -> dict:
    return {
        "id": plugin_id,
        "apiVersion": 1,
        "version": "0.1.0",
        "displayName": "Linear",
        "description": "Import Linear issues into Octopus projects.",
        "author": "Octopus",
        "categories": ["connector", "ui"],
        "capabilities": [
            "http.outbound",
            "secrets.read-ref",
            "plugin.state.read",
            "plugin.state.write",
            "issues.read",
            "issues.create",
            "projects.read",
            "organizations.read",
            "ui.page.register",
            "ui.detailTab.register",
            "instance.settings.register",
            "activity.log.write",
        ],
        "entrypoints": {
            "worker": "./dist/worker.js",
            "ui": "./dist/ui",
        },
        "instanceConfigSchema": {
            "type": "object",
            "required": ["apiTokenSecretRef"],
            "properties": {
                "apiTokenSecretRef": {
                    "type": "string",
                    "format": "secret-ref",
                }
            },
        },
        "ui": {
            "slots": [
                {
                    "type": "page",
                    "id": "linear-page",
                    "displayName": "Linear",
                    "exportName": "LinearPluginPage",
                    "routePath": "linear",
                },
                {
                    "type": "detailTab",
                    "id": "linear-issue-tab",
                    "displayName": "Linear",
                    "exportName": "LinearIssueTab",
                    "entityTypes": ["issue"],
                },
            ]
        },
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
        "tools": [
            {
                "name": "linear.search",
                "displayName": "Search Linear",
                "description": "Search Linear issues.",
                "parametersSchema": {"type": "object", "properties": {}},
            }
        ],
    }


def test_step29_plugin_paths_match_management_contract() -> None:
    assert PLUGIN_LIST_PATH == "/api/plugins"
    assert PLUGIN_AVAILABLE_PATH == "/api/plugins/available"
    assert PLUGIN_EXAMPLES_PATH == "/api/plugins/examples"
    assert PLUGIN_DETAIL_PATH == "/api/plugins/{pluginId}"
    assert PLUGIN_CONFIG_PATH == "/api/plugins/{pluginId}/config"
    assert PLUGIN_TOOLS_PATH == "/api/plugins/tools"
    assert (
        PLUGIN_TOOL_EXECUTE_PATH == "/api/plugins/{pluginId}/tools/{toolName}/execute"
    )
    assert PLUGIN_UI_CONTRIBUTIONS_PATH == "/api/plugins/ui/contributions"
    assert PLUGIN_UI_STREAM_PATH == "/api/plugins/{pluginId}/stream"
    assert PLUGIN_STATIC_PATH == "/api/plugins/{pluginId}/static/{assetPath:path}"


def test_step29_plugin_constants_cover_manifest_surface() -> None:
    assert PLUGIN_STATUSES == (
        "installed",
        "ready",
        "disabled",
        "error",
        "upgrade_pending",
        "uninstalled",
    )
    assert "agent.tools.register" in PLUGIN_CAPABILITIES
    assert "webhooks.receive" in PLUGIN_CAPABILITIES
    assert "detailTab" in PLUGIN_UI_SLOT_TYPES
    assert "settingsPage" in PLUGIN_UI_SLOT_TYPES


def test_step29_plugin_manifest_validator_accepts_full_manifest() -> None:
    manifest: Any = validate_plugin_manifest(_manifest())

    assert manifest["id"] == "linear.connector"
    assert manifest["apiVersion"] == 1
    assert manifest["entrypoints"]["worker"] == "./dist/worker.js"
    assert manifest["ui"]["slots"][0]["type"] == "page"
    assert manifest["jobs"][0]["jobKey"] == "sync"
    assert manifest["webhooks"][0]["endpointKey"] == "issue"
    assert manifest["tools"][0]["name"] == "linear.search"


def test_step29_plugin_manifest_validator_rejects_invalid_manifest() -> None:
    invalid_inputs = [
        {},
        {**_manifest(), "id": ""},
        {**_manifest(), "apiVersion": 2},
        {**_manifest(), "capabilities": ["unknown.capability"]},
        {**_manifest(), "ui": {"slots": [{"type": "unknown"}]}},
        {**_manifest(), "entrypoints": {"worker": ""}},
    ]

    for payload in invalid_inputs:
        try:
            validate_plugin_manifest(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected invalid plugin manifest: {payload}")


def test_step29_plugin_catalog_loads_bundled_manifests(tmp_path) -> None:
    root = tmp_path / "plugins"
    plugin_dir = root / "linear"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(_manifest()),
        encoding="utf-8",
    )
    (plugin_dir / "README.md").write_text("# Linear\n", encoding="utf-8")

    catalog = load_plugin_catalog(root)

    assert catalog.errors == []
    assert [entry.plugin_id for entry in catalog.entries] == ["linear.connector"]
    entry = catalog.entries[0]
    assert entry.display_name == "Linear"
    assert entry.example is True
    assert entry.manifest_path == plugin_dir / "manifest.json"
    assert entry.readme_path == plugin_dir / "README.md"


def test_step29_plugin_catalog_reports_invalid_manifests(tmp_path) -> None:
    root = tmp_path / "plugins"
    plugin_dir = root / "broken"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps({"id": "broken"}),
        encoding="utf-8",
    )

    catalog = load_plugin_catalog(root)

    assert catalog.entries == []
    assert len(catalog.errors) == 1
    assert catalog.errors[0].plugin_id == "broken"
    assert "apiVersion" in catalog.errors[0].message


async def test_step29_plugin_available_route_returns_catalog(tmp_path) -> None:
    root = tmp_path / "plugins"
    plugin_dir = root / "linear"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(_manifest()),
        encoding="utf-8",
    )
    application = create_app()
    application.state.plugin_catalog_root = root

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/api/plugins/available")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == [
        {
            "id": "linear.connector",
            "displayName": "Linear",
            "version": "0.1.0",
            "sourcePath": str(plugin_dir),
            "example": True,
            "manifest": validate_plugin_manifest(_manifest()),
        }
    ]
    assert payload["errors"] == []


async def test_step29_plugin_examples_route_filters_examples(tmp_path) -> None:
    root = tmp_path / "plugins"
    plugin_dir = root / "linear"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(_manifest()),
        encoding="utf-8",
    )
    application = create_app()
    application.state.plugin_catalog_root = root

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/api/plugins/examples")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["linear.connector"]
    assert payload["errors"] == []


async def test_step29_plugin_default_catalog_exposes_bundled_required_plugins() -> None:
    catalog = load_plugin_catalog(DEFAULT_PLUGIN_CATALOG_ROOT)
    ids = {entry.plugin_id for entry in catalog.entries}

    assert catalog.errors == []
    assert {
        "linear.connector",
        "plugin-authoring-smoke-example",
        "plugin-file-browser-example",
        "kitchen-sink",
        "github.connector",
        "git.local",
        "slack.connector",
        "jira.connector",
        "notion.connector",
    } <= ids

    application = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/api/plugins/available")

    assert response.status_code == 200
    route_ids = {item["id"] for item in response.json()["items"]}
    assert ids <= route_ids
