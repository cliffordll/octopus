from __future__ import annotations

import io

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_project_create_and_update_use_existing_endpoints() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "project-1", "name": "Console"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "project",
                "create",
                "--org-id",
                "org-1",
                "--name",
                "Console",
                "--status",
                "planned",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["project", "update", "project-1", "--status", "in_progress"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert requests[0].url.path == "/api/orgs/org-1/projects"
    assert requests[0].read() == b'{"name":"Console","status":"planned"}'
    assert requests[1].url.path == "/api/projects/project-1"
    assert requests[1].read() == b'{"status":"in_progress"}'


def test_project_commands_support_full_server_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "project-1", "name": "Console"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "project",
                "create",
                "--org-id",
                "org-1",
                "--name",
                "Console",
                "--goal-id",
                "goal-1",
                "--lead-agent-id",
                "agent-1",
                "--target-date",
                "2026-06-01",
                "--execution-workspace-policy",
                '{"mode":"isolated"}',
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            [
                "project",
                "update",
                "project-1",
                "--goal-id",
                "goal-2",
                "--lead-agent-id",
                "agent-2",
                "--target-date",
                "2026-07-01",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )

    assert requests[0].read() == (
        b'{"name":"Console","goalIds":["goal-1"],"leadAgentId":"agent-1",'
        b'"targetDate":"2026-06-01","executionWorkspacePolicy":{"mode":"isolated"}}'
    )
    assert requests[1].read() == (
        b'{"goalIds":["goal-2"],"leadAgentId":"agent-2","targetDate":"2026-07-01"}'
    )


def test_project_get_json_outputs_workspace_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/projects/project-1"
        return httpx.Response(
            200,
            json={
                "id": "project-1",
                "name": "Console",
                "codebase": {
                    "configured": True,
                    "repoUrl": "https://example.com/octopus.git",
                },
                "workspaces": [{"id": "workspace-1", "name": "Main"}],
                "primaryWorkspace": {"id": "workspace-1", "name": "Main"},
                "executionWorkspacePolicy": {
                    "enabled": True,
                    "defaultMode": "shared_workspace",
                },
            },
        )

    output = io.StringIO()
    assert (
        main(
            ["--json", "project", "get", "project-1"],
            client=ApiClient(transport=httpx.MockTransport(handler)),
            stdout=output,
        )
        == 0
    )
    assert "codebase" in output.getvalue()
    assert "workspaces" in output.getvalue()
    assert "executionWorkspacePolicy" in output.getvalue()


def test_project_resource_commands_use_attachment_routes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "attachment-1"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "project",
                "resource-add",
                "project-1",
                "--resource-id",
                "resource-1",
                "--role",
                "working_set",
            ],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert (
        main(
            ["project", "resource-remove", "project-1", "attachment-1"],
            client=client,
            stdout=io.StringIO(),
        )
        == 0
    )
    assert requests[0].url.path == "/api/projects/project-1/resources"
    assert requests[0].read() == b'{"resourceId":"resource-1","role":"working_set"}'
    assert requests[1].method == "DELETE"
    assert requests[1].url.path == "/api/projects/project-1/resources/attachment-1"


def test_project_resource_commands_support_sort_order() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "attachment-1"})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "project",
                "resource-add",
                "project-1",
                "--resource-id",
                "resource-1",
                "--sort-order",
                "3",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "project",
                "resource-update",
                "project-1",
                "attachment-1",
                "--sort-order",
                "4",
            ],
            client=client,
        )
        == 0
    )
    assert requests[0].read() == b'{"resourceId":"resource-1","sortOrder":3}'
    assert requests[1].read() == b'{"sortOrder":4}'
