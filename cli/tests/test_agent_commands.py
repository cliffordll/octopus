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
        main(["agent", "archive", "agent-1"], client=client, stdout=io.StringIO()) == 0
    )
    assert (
        main(["agent", "invoke", "agent-1"], client=client, stdout=io.StringIO()) == 0
    )
    assert requests[0].url.path == "/api/orgs/org-1/agents"
    assert (
        requests[0].read()
        == b'{"name":"Builder","role":"engineer","agentRuntimeType":"process","agentRuntimeConfig":{}}'
    )
    assert requests[1].url.path == "/api/agents/agent-1/pause"
    assert requests[2].url.path == "/api/agents/agent-1/archive"
    assert requests[3].url.path == "/api/agents/agent-1/heartbeat/invoke"


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


def test_agent_create_opencode_local_accepts_model_shortcut() -> None:
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
                "OpenCode Agent",
                "--role",
                "engineer",
                "--runtime",
                "opencode_local",
                "--model",
                "openai/gpt-5",
            ],
            client=client,
        )
        == 0
    )
    assert requests[0].read() == (
        b'{"name":"OpenCode Agent","role":"engineer",'
        b'"agentRuntimeType":"opencode_local",'
        b'"agentRuntimeConfig":{"model":"openai/gpt-5"}}'
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


def test_agent_instruction_commands_cover_step17_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "ok"})

    client = ApiClient(transport=httpx.MockTransport(handler))

    assert main(["agent", "instructions", "agent-1"], client=client) == 0
    assert (
        main(
            ["agent", "instruction-file", "agent-1", "--path", "SOUL.md"], client=client
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "instruction-file-update",
                "agent-1",
                "--path",
                "SOUL.md",
                "--content",
                "# Soul",
                "--clear-legacy-prompt-template",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "instructions-update",
                "agent-1",
                "--mode",
                "managed",
                "--entry-file",
                "SOUL.md",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "agent",
                "instructions-path",
                "agent-1",
                "--path",
                "SOUL.md",
                "--agent-runtime-config-key",
                "instructionsPath",
            ],
            client=client,
        )
        == 0
    )

    assert [request.url.path for request in requests] == [
        "/api/agents/agent-1/instructions-bundle",
        "/api/agents/agent-1/instructions-bundle/file",
        "/api/agents/agent-1/instructions-bundle/file",
        "/api/agents/agent-1/instructions-bundle",
        "/api/agents/agent-1/instructions-path",
    ]
    assert requests[1].url.params["path"] == "SOUL.md"
    assert requests[2].read() == (
        b'{"path":"SOUL.md","content":"# Soul","clearLegacyPromptTemplate":true}'
    )
    assert requests[3].read() == b'{"mode":"managed","entryFile":"SOUL.md"}'
    assert requests[4].read() == (
        b'{"path":"SOUL.md","agentRuntimeConfigKey":"instructionsPath"}'
    )


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


def test_heartbeat_debug_fetches_run_and_events() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/events"):
            return httpx.Response(
                200,
                json=[
                    {
                        "seq": 1,
                        "eventType": "runtime.stderr",
                        "level": "error",
                        "message": "model missing",
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "id": "run-1",
                "status": "failed",
                "errorCode": "runtime_error",
                "error": "Runtime failed",
                "stdoutExcerpt": "boot ok",
                "stderrExcerpt": "model missing",
                "contextSnapshot": {
                    "workspace": {"executionWorkspaceId": "workspace-1"}
                },
            },
        )

    stdout = io.StringIO()
    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["heartbeat", "debug", "run-1"], client=client, stdout=stdout) == 0
    output = stdout.getvalue()
    assert "failed" in output
    assert "runtime_error" in output
    assert "model missing" in output
    assert requests[0].url.path == "/api/heartbeat-runs/run-1"
    assert requests[1].url.path == "/api/heartbeat-runs/run-1/events"


def test_heartbeat_observability_commands_use_existing_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/log"):
            return httpx.Response(
                200,
                json={"content": "raw run log", "endOffset": 11, "eof": True},
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": "op-1",
                    "phase": "setup",
                    "status": "failed",
                    "command": "npm test",
                    "stderrExcerpt": "workspace stderr",
                }
            ],
        )

    stdout = io.StringIO()
    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            ["heartbeat", "log", "run-1", "--offset", "10", "--limit-bytes", "64"],
            client=client,
            stdout=stdout,
        )
        == 0
    )
    assert (
        main(
            ["heartbeat", "workspace-operations", "run-1"],
            client=client,
            stdout=stdout,
        )
        == 0
    )
    output = stdout.getvalue()
    assert "raw run log" in output
    assert "workspace stderr" in output
    assert requests[0].url.path == "/api/heartbeat-runs/run-1/log"
    assert requests[0].url.params["offset"] == "10"
    assert requests[0].url.params["limitBytes"] == "64"
    assert requests[1].url.path == "/api/heartbeat-runs/run-1/workspace-operations"


def test_run_intelligence_commands_use_existing_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/events"):
            return httpx.Response(200, json=[{"eventType": "runtime.stderr"}])
        if request.url.path.endswith("/log"):
            return httpx.Response(200, json={"content": "run intelligence log"})
        return httpx.Response(
            200,
            json={
                "run": {"id": "run-1", "status": "failed"},
                "agentName": "Builder",
                "orgName": "OCT",
            },
        )

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "run-intelligence",
                "list",
                "--org-id",
                "org-1",
                "--status",
                "failed",
                "--agent-id",
                "agent-1",
                "--limit",
                "5",
            ],
            client=client,
        )
        == 0
    )
    assert main(["run-intelligence", "get", "run-1"], client=client) == 0
    assert main(["run-intelligence", "events", "run-1"], client=client) == 0
    assert main(["run-intelligence", "log", "run-1"], client=client) == 0
    assert requests[0].url.path == "/api/run-intelligence/orgs/org-1/runs"
    assert requests[0].url.params["status"] == "failed"
    assert requests[0].url.params["agentId"] == "agent-1"
    assert requests[0].url.params["limit"] == "5"
    assert requests[1].url.path == "/api/run-intelligence/runs/run-1"
    assert requests[2].url.path == "/api/run-intelligence/runs/run-1/events"
    assert requests[3].url.path == "/api/run-intelligence/runs/run-1/log"
