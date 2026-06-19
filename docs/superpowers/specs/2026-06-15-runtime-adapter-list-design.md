# Runtime Adapter List Design

## Goal

Expose the runtime adapters actually registered by the server and make agent
creation and configuration use that server-provided list.

## API

Add `GET /api/orgs/{orgId}/adapters`. The route requires organization access
and returns adapters in registry order. Each item contains:

- `type`: runtime contract value such as `codex_local`
- `displayName`: human-readable metadata name, falling back to `type`
- `metadata`: the adapter metadata returned by the existing adapter metadata API

Only adapters in the executable registry are returned. Known but unavailable
compatibility types are excluded.

## UI

Add `agentsApi.adapters(orgId)`. Agent creation and configuration query this
endpoint and render runtime options from the response. The current runtime is
preserved while data loads. A failed query displays an error and disables the
relevant save/create action instead of falling back to a duplicated hard-coded
list.

## Testing

- Contract test verifies the path and registered adapter list.
- UI API test verifies the request and response shape.
- Agent creation test verifies options come from the API.
- Agent configuration test verifies the runtime selector uses the same list.
