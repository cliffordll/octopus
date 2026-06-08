from __future__ import annotations

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_activity_commands_cover_query_and_linked_run_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "activity",
                "list",
                "--org-id",
                "org-1",
                "--entity-type",
                "goal",
                "--entity-id",
                "goal-1",
                "--action",
                "goal.updated",
                "--limit",
                "25",
            ],
            client=client,
        )
        == 0
    )
    assert main(["activity", "issue", "issue-1"], client=client) == 0
    assert main(["activity", "issue-runs", "issue-1"], client=client) == 0
    assert main(["activity", "run-issues", "run-1"], client=client) == 0

    assert [request.url.path for request in requests] == [
        "/api/orgs/org-1/activity",
        "/api/issues/issue-1/activity",
        "/api/issues/issue-1/runs",
        "/api/heartbeat-runs/run-1/issues",
    ]
    assert "entityType=goal" in str(requests[0].url)
    assert "entityId=goal-1" in str(requests[0].url)
    assert "action=goal.updated" in str(requests[0].url)
    assert "limit=25" in str(requests[0].url)


def test_activity_create_posts_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "activity-1"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "activity",
                "create",
                "--org-id",
                "org-1",
                "--action",
                "goal.updated",
                "--entity-type",
                "goal",
                "--entity-id",
                "goal-1",
                "--actor-agent-id",
                "agent-1",
                "--actor-id",
                "agent-1",
                "--details",
                '{"note":"updated"}',
            ],
            client=client,
        )
        == 0
    )

    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/orgs/org-1/activity"
    assert requests[0].read() == (
        b'{"action":"goal.updated","entityType":"goal","entityId":"goal-1",'
        b'"actorId":"agent-1","agentId":"agent-1","details":{"note":"updated"}}'
    )
