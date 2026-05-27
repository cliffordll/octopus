from __future__ import annotations

import io

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_issue_list_passes_organization_and_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/orgs/org-1/issues"
        assert request.url.params["status"] == "in_review"
        return httpx.Response(200, json=[{"identifier": "OCT-1", "title": "Review"}])

    output = io.StringIO()
    result = main(
        ["issue", "list", "--org-id", "org-1", "--status", "in_review"],
        client=ApiClient(transport=httpx.MockTransport(handler)),
        stdout=output,
    )

    assert result == 0
    assert "OCT-1" in output.getvalue()


def test_issue_comment_and_review_post_payloads() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "issue-1", "title": "Review"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["issue", "comment-add", "issue-1", "--body", "Ship it"], client=client) == 0
    assert main(["issue", "review", "issue-1", "--decision", "approve"], client=client) == 0
    assert requests[0].url.path == "/api/issues/issue-1/comments"
    assert requests[0].read() == b'{"body":"Ship it"}'
    assert requests[1].url.path == "/api/issues/issue-1/review-decision"
    assert requests[1].read() == b'{"decision":"approve"}'
