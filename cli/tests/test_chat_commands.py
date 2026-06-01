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


def test_chat_step16_commands_use_extended_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "chat-1"})

    client = ApiClient(transport=httpx.MockTransport(handler))

    assert (
        main(
            [
                "chat",
                "list",
                "--org-id",
                "org-1",
                "--status",
                "archived",
                "--q",
                "deploy",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            [
                "chat",
                "update",
                "chat-1",
                "--title",
                "Deploy",
                "--status",
                "resolved",
                "--no-plan-mode",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["chat", "user-state", "chat-1", "--pinned", "--read"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            [
                "chat",
                "context-link",
                "chat-1",
                "--entity-type",
                "project",
                "--entity-id",
                "project-1",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["chat", "project-context", "chat-1", "--project-id", "project-1"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            [
                "chat",
                "convert-to-issue",
                "chat-1",
                "--proposal",
                '{"title":"Ship","description":"Deploy"}',
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            [
                "chat",
                "resolve-operation",
                "chat-1",
                "message-1",
                "--action",
                "approve",
                "--note",
                "OK",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(["chat", "stream-stop", "chat-1"], client=client, stdout=io.StringIO())
        == 0
    )

    assert (
        str(requests[0].url)
        == "http://127.0.0.1:8000/api/orgs/org-1/chats?status=archived&q=deploy"
    )
    assert requests[1].url.path == "/api/chats/chat-1"
    assert (
        requests[1].read() == b'{"title":"Deploy","status":"resolved","planMode":false}'
    )
    assert requests[2].url.path == "/api/chats/chat-1/user-state"
    assert requests[2].read() == b'{"pinned":true,"unread":false}'
    assert requests[3].url.path == "/api/chats/chat-1/context-links"
    assert requests[4].url.path == "/api/chats/chat-1/project-context"
    assert requests[5].url.path == "/api/chats/chat-1/convert-to-issue"
    assert requests[5].read() == b'{"proposal":{"title":"Ship","description":"Deploy"}}'
    assert (
        requests[6].url.path
        == "/api/chats/chat-1/messages/message-1/operation-proposal/resolve"
    )
    assert requests[6].read() == b'{"action":"approve","decisionNote":"OK"}'
    assert requests[7].url.path == "/api/chats/chat-1/messages/stream/stop"


def test_chat_attachment_upload_uses_multipart_route(tmp_path) -> None:
    upload = tmp_path / "note.txt"
    upload.write_text("chat attachment", encoding="utf-8")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={"id": "attachment-1", "assetId": "asset-1"})

    assert (
        main(
            [
                "chat",
                "attachment-upload",
                "--org-id",
                "org-1",
                "chat-1",
                "--message-id",
                "message-1",
                "--file",
                str(upload),
            ],
            client=ApiClient(transport=httpx.MockTransport(handler)),
        )
        == 0
    )
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/orgs/org-1/chats/chat-1/attachments"
    body = requests[0].read()
    assert b'name="messageId"' in body
    assert b"message-1" in body
