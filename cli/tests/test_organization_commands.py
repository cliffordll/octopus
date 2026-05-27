from __future__ import annotations

import io

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_organization_list_json_output() -> None:
    client = ApiClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=[{"id": "org-1", "name": "Core"}])
        )
    )
    output = io.StringIO()

    result = main(["--json", "organization", "list"], client=client, stdout=output)

    assert result == 0
    assert '"name": "Core"' in output.getvalue()


def test_organization_create_posts_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/orgs"
        assert request.read() == b'{"name":"Core"}'
        return httpx.Response(200, json={"id": "org-1", "name": "Core"})

    output = io.StringIO()
    result = main(
        ["organization", "create", "--name", "Core"],
        client=ApiClient(transport=httpx.MockTransport(handler)),
        stdout=output,
    )

    assert result == 0
    assert "Core" in output.getvalue()
