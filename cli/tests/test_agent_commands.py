from __future__ import annotations

import io

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_agent_create_lifecycle_and_invoke_use_existing_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "agent-1", "status": "idle"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "agent",
                "create",
                "--org-id",
                "org-1",
                "--name",
                "Builder",
                "--role",
                "engineer",
                "--runtime",
                "process",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert main(["agent", "pause", "agent-1"], client=client, stdout=io.StringIO()) == 0
    assert (
        main(["agent", "invoke", "agent-1"], client=client, stdout=io.StringIO()) == 0
    )
    assert requests[0].url.path == "/api/orgs/org-1/agents"
    assert (
        requests[0].read()
        == b'{"name":"Builder","role":"engineer","agentRuntimeType":"process","agentRuntimeConfig":{}}'
    )
    assert requests[1].url.path == "/api/agents/agent-1/pause"
    assert requests[2].url.path == "/api/agents/agent-1/heartbeat/invoke"


def test_agent_bootstrap_ceo_only_creates_for_empty_organization() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={"id": "agent-ceo", "role": "ceo"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "agent",
                "bootstrap-ceo",
                "--org-id",
                "org-1",
                "--name",
                "Founding CEO",
                "--runtime",
                "codex_local",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/api/orgs/org-1/agents"
    assert requests[1].read() == (
        b'{"name":"Founding CEO","role":"ceo","agentRuntimeType":"codex_local",'
        b'"agentRuntimeConfig":{}}'
    )


def test_agent_bootstrap_ceo_rejects_organization_with_existing_agents() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[{"id": "agent-1", "role": "engineer"}])

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "agent",
                "bootstrap-ceo",
                "--org-id",
                "org-1",
                "--name",
                "Founding CEO",
                "--runtime",
                "process",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 1
    )
    assert len(requests) == 1


def test_agent_supported_read_commands_use_existing_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["agent", "configuration", "agent-1"], client=client) == 0
    assert main(["agent", "config-revisions", "agent-1"], client=client) == 0
    assert main(["agent", "config-revision", "agent-1", "rev-1"], client=client) == 0
    assert main(["agent", "runtime-state", "agent-1"], client=client) == 0
    assert main(["agent", "task-sessions", "agent-1"], client=client) == 0

    assert [request.url.path for request in requests] == [
        "/api/agents/agent-1/configuration",
        "/api/agents/agent-1/config-revisions",
        "/api/agents/agent-1/config-revisions/rev-1",
        "/api/agents/agent-1/runtime-state",
        "/api/agents/agent-1/task-sessions",
    ]


def test_agent_management_commands_cover_configuration_and_session_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "agent-1", "status": "idle"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["agent", "name-suggestion", "--org-id", "org-1"], client=client) == 0
    assert main(["agent", "configurations", "--org-id", "org-1"], client=client) == 0
    assert (
        main(
            [
                "agent",
                "update",
                "agent-1",
                "--title",
                "Staff Engineer",
                "--reports-to",
                "agent-ceo",
                "--budget-monthly-cents",
                "120000",
            ],
            client=client,
        )
        == 0
    )
    assert main(["agent", "rollback", "agent-1", "revision-1"], client=client) == 0
    assert (
        main(
            [
                "agent",
                "reset-session",
                "agent-1",
                "--task-key",
                "task-1",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "wakeup",
                "agent-1",
                "--reason",
                "manual",
                "--idempotency-key",
                "once",
            ],
            client=client,
        )
        == 0
    )

    assert [request.url.path for request in requests] == [
        "/api/orgs/org-1/agents/name-suggestion",
        "/api/orgs/org-1/agent-configurations",
        "/api/agents/agent-1",
        "/api/agents/agent-1/config-revisions/revision-1/rollback",
        "/api/agents/agent-1/runtime-state/reset-session",
        "/api/agents/agent-1/wakeup",
    ]
    assert requests[2].read() == (
        b'{"title":"Staff Engineer","reportsTo":"agent-ceo",'
        b'"budgetMonthlyCents":120000}'
    )
    assert requests[4].read() == b'{"taskKey":"task-1"}'
    assert requests[5].read() == b'{"idempotencyKey":"once","reason":"manual"}'


def test_agent_create_and_update_cover_step14_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "agent-1"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "agent",
                "create",
                "--org-id",
                "org-1",
                "--name",
                "Builder",
                "--role",
                "engineer",
                "--runtime",
                "codex_local",
                "--icon",
                "hammer",
                "--desired-skill",
                "review",
                "--metadata",
                '{"tier":"gold"}',
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "update",
                "agent-1",
                "--icon",
                "rocket",
                "--desired-skill",
                "debug",
                "--status",
                "idle",
                "--spent-monthly-cents",
                "42",
                "--replace-agent-runtime-config",
                "--metadata",
                '{"source":"cli"}',
            ],
            client=client,
        )
        == 0
    )

    assert requests[0].read() == (
        b'{"name":"Builder","role":"engineer","agentRuntimeType":"codex_local",'
        b'"agentRuntimeConfig":{},"icon":"hammer","desiredSkills":["review"],'
        b'"metadata":{"tier":"gold"}}'
    )
    assert requests[1].read() == (
        b'{"icon":"rocket","status":"idle","spentMonthlyCents":42,'
        b'"desiredSkills":["debug"],"metadata":{"source":"cli"},'
        b'"replaceAgentRuntimeConfig":true}'
    )


def test_agent_adapter_commands_cover_step14_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "agent",
                "adapter-models",
                "--org-id",
                "org-1",
                "--runtime",
                "codex_local",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "adapter-metadata",
                "--org-id",
                "org-1",
                "--runtime",
                "codex_local",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "adapter-quota-windows",
                "--org-id",
                "org-1",
                "--runtime",
                "codex_local",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "adapter-test-environment",
                "--org-id",
                "org-1",
                "--runtime",
                "http",
                "--runtime-config",
                '{"url":"https://example.test"}',
            ],
            client=client,
        )
        == 0
    )

    assert [request.url.path for request in requests] == [
        "/api/orgs/org-1/adapters/codex_local/models",
        "/api/orgs/org-1/adapters/codex_local",
        "/api/orgs/org-1/adapters/codex_local/quota-windows",
        "/api/orgs/org-1/adapters/http/test-environment",
    ]
    assert requests[3].read() == (
        b'{"agentRuntimeConfig":{"url":"https://example.test"}}'
    )


def test_agent_skills_commands_cover_step14_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["agent", "skills", "agent-1"], client=client) == 0
    assert (
        main(
            ["agent", "skills-sync", "agent-1", "--desired-skill", "review"],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "skills-enable",
                "agent-1",
                "--skill",
                "debug",
                "--skill",
                "plan",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "private-skill",
                "agent-1",
                "--name",
                "Incident response",
                "--slug",
                "incident-response",
                "--description",
                "Handle incidents",
                "--markdown",
                "# Incident",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            ["agent", "skills-analytics", "agent-1", "--window-days", "14"],
            client=client,
        )
        == 0
    )

    assert [request.url.path for request in requests] == [
        "/api/agents/agent-1/skills",
        "/api/agents/agent-1/skills/sync",
        "/api/agents/agent-1/skills/enable",
        "/api/agents/agent-1/skills/private",
        "/api/agents/agent-1/skills/analytics",
    ]
    assert requests[1].read() == b'{"desiredSkills":["review"]}'
    assert requests[2].read() == b'{"skills":["debug","plan"]}'
    assert requests[3].read() == (
        b'{"name":"Incident response","slug":"incident-response",'
        b'"description":"Handle incidents","markdown":"# Incident"}'
    )
    assert "windowDays=14" in str(requests[4].url)


def test_heartbeat_runs_list_and_events_use_existing_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            ["heartbeat", "list", "--org-id", "org-1", "--agent-id", "agent-1"],
            client=client,
        )
        == 0
    )
    assert (
        main(
            ["heartbeat", "events", "run-1", "--after-seq", "3", "--limit", "20"],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "heartbeat",
                "run",
                "--agent-id",
                "agent-1",
                "--idempotency-key",
                "once",
                "--reason",
                "manual",
                "--source",
                "on_demand",
                "--trigger-detail",
                "manual",
                "--payload",
                '{"requestedBy":"cli"}',
                "--force-fresh-session",
            ],
            client=client,
        )
        == 0
    )
    assert main(["heartbeat", "cancel", "run-1"], client=client) == 0
    assert main(["heartbeat", "retry", "run-1"], client=client) == 0
    assert "/api/orgs/org-1/heartbeat-runs?agentId=agent-1" in str(requests[0].url)
    assert "/api/heartbeat-runs/run-1/events?afterSeq=3&limit=20" in str(
        requests[1].url
    )
    assert requests[2].method == "POST"
    assert requests[2].url.path == "/api/agents/agent-1/wakeup"
    assert requests[2].read() == (
        b'{"idempotencyKey":"once","reason":"manual","source":"on_demand",'
        b'"triggerDetail":"manual","payload":{"requestedBy":"cli"},'
        b'"forceFreshSession":true}'
    )
    assert requests[3].method == "POST"
    assert requests[3].url.path == "/api/heartbeat-runs/run-1/cancel"
    assert requests[4].method == "POST"
    assert requests[4].url.path == "/api/heartbeat-runs/run-1/retry"
