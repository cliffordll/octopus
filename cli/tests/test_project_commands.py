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
