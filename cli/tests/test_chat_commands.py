from __future__ import annotations

import io

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_chat_create_and_message_use_existing_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "chat-1"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "chat",
                "create",
                "--org-id",
                "org-1",
                "--title",
                "Support",
                "--agent-id",
                "agent-1",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["chat", "message", "chat-1", "--body", "Ready?"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert requests[0].url.path == "/api/orgs/org-1/chats"
    assert requests[0].read() == b'{"title":"Support","preferredAgentId":"agent-1"}'
    assert requests[1].url.path == "/api/chats/chat-1/messages"
    assert requests[1].read() == b'{"body":"Ready?"}'
