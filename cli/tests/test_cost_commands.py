from __future__ import annotations

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_cost_report_posts_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "cost-1"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "cost",
                "report",
                "--org-id",
                "org-1",
                "--agent-id",
                "agent-1",
                "--provider",
                "openai",
                "--model",
                "gpt-5",
                "--biller",
                "openrouter",
                "--cost-cents",
                "42",
                "--metadata",
                '{"safe":"visible"}',
            ],
            client=client,
        )
        == 0
    )

    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/orgs/org-1/cost-events"
    assert requests[0].read() == (
        b'{"agentId":"agent-1","provider":"openai","model":"gpt-5",'
        b'"biller":"openrouter","costCents":42,"metadata":{"safe":"visible"}}'
    )


def test_cost_query_commands_cover_summary_and_dimensions() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["cost", "summary", "--org-id", "org-1"], client=client) == 0
    assert (
        main(
            [
                "cost",
                "by-agent",
                "--org-id",
                "org-1",
                "--start-time",
                "2026-06-01T00:00:00Z",
            ],
            client=client,
        )
        == 0
    )
    assert main(["cost", "by-provider", "--org-id", "org-1"], client=client) == 0
    assert main(["cost", "by-biller", "--org-id", "org-1"], client=client) == 0
    assert main(["cost", "by-project", "--org-id", "org-1"], client=client) == 0

    assert [request.url.path for request in requests] == [
        "/api/orgs/org-1/costs/summary",
        "/api/orgs/org-1/costs/by-agent",
        "/api/orgs/org-1/costs/by-provider",
        "/api/orgs/org-1/costs/by-biller",
        "/api/orgs/org-1/costs/by-project",
    ]
    assert "startTime=2026-06-01T00%3A00%3A00Z" in str(requests[1].url)
