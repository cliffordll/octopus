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


def test_heartbeat_runs_list_and_events_use_existing_routes() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(str(request.url))
        return httpx.Response(200, json=[])

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            ["heartbeat", "list", "--org-id", "org-1", "--agent-id", "agent-1"],
            client=client,
        )
        == 0
    )
    assert main(["heartbeat", "events", "run-1"], client=client) == 0
    assert "/api/orgs/org-1/heartbeat-runs?agentId=agent-1" in paths[0]
    assert paths[1].endswith("/api/heartbeat-runs/run-1/events")
