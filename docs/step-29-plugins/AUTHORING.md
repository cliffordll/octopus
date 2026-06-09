# Step 29 Plugin Authoring And Operations

## Bundled Directory

Bundled plugin fixtures live under `server/plugins/bundled/`. Each plugin uses this layout:

```text
server/plugins/bundled/<plugin-id>/
  manifest.json
  README.md
  dist/
    worker.js
    ui/
      plugin.js
```

The server catalog defaults to `server/plugins/bundled/`. Tests may override the catalog root with `application.state.plugin_catalog_root`.

## Manifest Boundary

`manifest.json` is the source of truth for:

- plugin identity, version, display name, author, and categories
- worker and UI entrypoints
- declared capabilities
- instance config schema
- UI slots
- jobs, webhooks, and tools

The server validates manifest structure before exposing a plugin in the catalog or installing it.

## Install And Configure

Install uses `POST /api/plugins/install` with:

- `manifest`
- `sourceType`
- `sourceLocator`

Config uses `POST /api/plugins/{pluginId}/config` with `configJson`.

Secret values are not stored directly in plugin config. Config should store secret references such as `secret:<key>` until the Step 30 access and secret boundary is complete.

## Worker And Bridge

The worker manager currently exposes the host call boundary for:

- `validateConfig`
- `handleWebhook`
- `executeTool`
- `getData`
- `performAction`

The UI bridge routes are:

- `GET /api/plugins/ui/contributions`
- `POST /api/plugins/{pluginId}/data/{key}`
- `POST /api/plugins/{pluginId}/actions/{key}`
- `GET /api/plugins/{pluginId}/stream`
- `GET /api/plugins/{pluginId}/static/{assetPath}`

Plugin UI is trusted same-origin code. It is not a sandbox and does not get a shared host component library in Step 29.

## Debugging

Use plugin logs and lifecycle status first:

- `GET /api/plugins`
- `GET /api/plugins/{pluginId}/logs`
- `GET /api/plugins/{pluginId}/jobs`

For webhook and job tests, inspect `plugin_webhook_deliveries`, `plugin_job_runs`, and `plugin_logs` through the contract tests or database tooling.

## Required Integration Fixtures

Step 29 includes bundled fixtures for:

- Linear
- GitHub
- Slack
- Jira
- Notion
- Plugin Authoring Smoke Example
- File Browser Example
- Kitchen Sink Example

GitHub, Slack, Jira, and Notion fixtures define the required capability/config/UI boundaries. They do not claim production-grade external synchronization until their provider-specific auth, webhook validation, data mapping, and recovery behavior are implemented.
