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


def test_issue_commands_support_full_server_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "issue-1", "title": "Review"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "issue",
                "list",
                "--org-id",
                "org-1",
                "--project-id",
                "project-1",
                "--goal-id",
                "goal-1",
                "--parent-id",
                "parent-1",
                "--origin-kind",
                "manual",
                "--origin-id",
                "origin-1",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "issue",
                "create",
                "--org-id",
                "org-1",
                "--title",
                "Review",
                "--project-id",
                "project-1",
                "--goal-id",
                "goal-1",
                "--assignee-agent-id",
                "agent-1",
                "--reviewer-agent-id",
                "agent-2",
                "--created-by-agent-id",
                "agent-1",
                "--parent-id",
                "parent-1",
                "--request-depth",
                "2",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "issue",
                "update",
                "issue-1",
                "--goal-id",
                "goal-2",
                "--reviewer-user-id",
                "user-1",
            ],
            client=client,
        )
        == 0
    )

    assert "projectId=project-1" in str(requests[0].url)
    assert "goalId=goal-1" in str(requests[0].url)
    assert "parentId=parent-1" in str(requests[0].url)
    assert "originKind=manual" in str(requests[0].url)
    assert requests[1].read() == (
        b'{"title":"Review","projectId":"project-1","goalId":"goal-1",'
        b'"parentId":"parent-1","assigneeAgentId":"agent-1",'
        b'"reviewerAgentId":"agent-2","createdByAgentId":"agent-1",'
        b'"requestDepth":2}'
    )
    assert requests[2].read() == b'{"goalId":"goal-2","reviewerUserId":"user-1"}'


def test_issue_list_sends_route_supported_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/orgs/org-1/issues"
        assert "projectId=project-1" in str(request.url)
        assert "parentId=parent-1" in str(request.url)
        assert "assigneeUserId" not in str(request.url)
        assert "reviewerAgentId" not in str(request.url)
        assert "reviewerUserId" not in str(request.url)
        return httpx.Response(200, json=[])

    assert (
        main(
            [
                "issue",
                "list",
                "--org-id",
                "org-1",
                "--project-id",
                "project-1",
                "--parent-id",
                "parent-1",
            ],
            client=ApiClient(transport=httpx.MockTransport(handler)),
        )
        == 0
    )


def test_issue_checkout_and_heartbeat_context_commands() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/heartbeat-context"):
            return httpx.Response(200, json={"issueId": "issue-1"})
        return httpx.Response(200, json={"id": "issue-1", "assigneeAgentId": "agent-1"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "issue",
                "checkout",
                "issue-1",
                "--agent-id",
                "agent-1",
                "--expected-status",
                "todo",
                "--expected-status",
                "in_progress",
            ],
            client=client,
        )
        == 0
    )
    assert main(["issue", "heartbeat-context", "issue-1"], client=client) == 0

    assert requests[0].url.path == "/api/issues/issue-1/checkout"
    assert requests[0].read() == (
        b'{"agentId":"agent-1","expectedStatuses":["todo","in_progress"]}'
    )
    assert requests[1].url.path == "/api/issues/issue-1/heartbeat-context"


def test_issue_get_json_outputs_work_products() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/issues/issue-1"
        return httpx.Response(
            200,
            json={
                "id": "issue-1",
                "title": "Review",
                "workProducts": [
                    {
                        "id": "wp-1",
                        "title": "Pull request",
                        "type": "pull_request",
                        "executionWorkspaceId": "exec-1",
                    }
                ],
            },
        )

    output = io.StringIO()
    assert (
        main(
            ["--json", "issue", "get", "issue-1"],
            client=ApiClient(transport=httpx.MockTransport(handler)),
            stdout=output,
        )
        == 0
    )
    assert "workProducts" in output.getvalue()
    assert "exec-1" in output.getvalue()


def test_issue_execute_and_runs_use_issue_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/runs"):
            return httpx.Response(200, json=[{"id": "run-1", "status": "queued"}])
        return httpx.Response(202, json={"id": "run-1", "status": "queued"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["issue", "execute", "issue-1"], client=client) == 0
    assert main(["issue", "runs", "issue-1"], client=client) == 0

    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/issues/issue-1/execute"
    assert requests[0].read() == b"{}"
    assert requests[1].method == "GET"
    assert requests[1].url.path == "/api/issues/issue-1/runs"


def test_issue_comment_and_review_post_payloads() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "issue-1", "title": "Review"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(["issue", "comment", "issue-1", "--body", "Ship it"], client=client) == 0
    )
    assert (
        main(["issue", "comment-add", "issue-1", "--body", "Compatible"], client=client)
        == 0
    )
    assert (
        main(["issue", "review", "issue-1", "--decision", "approve"], client=client)
        == 0
    )
    assert requests[0].url.path == "/api/issues/issue-1/comments"
    assert requests[0].read() == b'{"body":"Ship it"}'
    assert requests[1].url.path == "/api/issues/issue-1/comments"
    assert requests[1].read() == b'{"body":"Compatible"}'
    assert requests[2].url.path == "/api/issues/issue-1/review-decision"
    assert requests[2].read() == b'{"decision":"approve"}'


def test_issue_attachment_commands_use_storage_routes(tmp_path) -> None:
    upload = tmp_path / "evidence.txt"
    upload.write_text("attachment body", encoding="utf-8")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(
            200,
            json={
                "id": "attachment-1",
                "assetId": "asset-1",
                "contentPath": "/api/assets/asset-1/content",
            },
        )

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert main(["issue", "attachments", "issue-1"], client=client) == 0
    assert (
        main(
            [
                "issue",
                "attachment-upload",
                "--org-id",
                "org-1",
                "issue-1",
                "--file",
                str(upload),
                "--usage",
                "evidence",
            ],
            client=client,
        )
        == 0
    )
    assert main(["issue", "attachment-delete", "attachment-1"], client=client) == 0

    assert requests[0].method == "GET"
    assert requests[0].url.path == "/api/issues/issue-1/attachments"
    assert requests[1].method == "POST"
    assert requests[1].url.path == "/api/orgs/org-1/issues/issue-1/attachments"
    assert b'name="usage"' in requests[1].read()
    assert requests[2].method == "DELETE"
    assert requests[2].url.path == "/api/attachments/attachment-1"
