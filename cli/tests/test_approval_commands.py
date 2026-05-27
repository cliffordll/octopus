from __future__ import annotations

import io

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_approval_create_posts_parsed_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/orgs/org-1/approvals"
        assert (
            request.read() == b'{"type":"chat_operation","payload":{"action":"deploy"}}'
        )
        return httpx.Response(200, json={"id": "approval-1", "status": "pending"})

    result = main(
        [
            "--json",
            "approval",
            "create",
            "--org-id",
            "org-1",
            "--type",
            "chat_operation",
            "--payload",
            '{"action":"deploy"}',
        ],
        client=ApiClient(transport=httpx.MockTransport(handler)),
        stdout=io.StringIO(),
    )

    assert result == 0


def test_approval_decision_and_resubmit_use_existing_endpoints() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"id": "approval-1", "status": "approved"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(["approval", "approve", "approval-1", "--note", "OK"], client=client) == 0
    )
    assert (
        main(["approval", "resubmit", "approval-1", "--payload", "{}"], client=client)
        == 0
    )
    assert paths == [
        "/api/approvals/approval-1/approve",
        "/api/approvals/approval-1/resubmit",
    ]
