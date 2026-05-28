from __future__ import annotations

import io

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_goal_create_update_and_dependencies_use_goal_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "goal-1", "title": "Ship"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "goal",
                "create",
                "--org-id",
                "org-1",
                "--title",
                "Ship",
                "--level",
                "organization",
                "--status",
                "active",
                "--owner-agent-id",
                "agent-1",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["goal", "update", "goal-1", "--status", "achieved"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["goal", "dependencies", "goal-1"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert requests[0].url.path == "/api/orgs/org-1/goals"
    assert requests[0].read() == (
        b'{"title":"Ship","level":"organization","status":"active",'
        b'"ownerAgentId":"agent-1"}'
    )
    assert requests[1].url.path == "/api/goals/goal-1"
    assert requests[1].read() == b'{"status":"achieved"}'
    assert requests[2].url.path == "/api/goals/goal-1/dependencies"


def test_goal_list_get_and_delete_use_existing_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "goal-1", "title": "Ship"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["goal", "list", "--org-id", "org-1"], client=client) == 0
    assert main(["goal", "get", "goal-1"], client=client) == 0
    assert main(["goal", "delete", "goal-1"], client=client) == 0
    assert requests[0].url.path == "/api/orgs/org-1/goals"
    assert requests[1].url.path == "/api/goals/goal-1"
    assert requests[2].method == "DELETE"
    assert requests[2].url.path == "/api/goals/goal-1"
