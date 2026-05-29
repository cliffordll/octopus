from __future__ import annotations

import io

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_messenger_commands_use_step16_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    client = ApiClient(transport=httpx.MockTransport(handler))

    assert (
        main(
            ["messenger", "threads", "--org-id", "org-1"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["messenger", "chat", "--org-id", "org-1", "chat-1"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            [
                "messenger",
                "read",
                "--org-id",
                "org-1",
                "chat:chat-1",
                "--last-read-at",
                "2026-05-29T00:00:00",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["messenger", "issues", "--org-id", "org-1"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["messenger", "approvals", "--org-id", "org-1"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["messenger", "system", "--org-id", "org-1", "failed-runs"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )

    assert [request.url.path for request in requests] == [
        "/api/orgs/org-1/messenger/threads",
        "/api/orgs/org-1/messenger/chat/chat-1",
        "/api/orgs/org-1/messenger/threads/chat:chat-1/read",
        "/api/orgs/org-1/messenger/issues",
        "/api/orgs/org-1/messenger/approvals",
        "/api/orgs/org-1/messenger/system/failed-runs",
    ]
    assert requests[2].read() == b'{"lastReadAt":"2026-05-29T00:00:00"}'
