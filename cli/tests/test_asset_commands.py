from __future__ import annotations

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_asset_content_can_be_written_to_output(tmp_path) -> None:
    output = tmp_path / "asset.txt"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/assets/asset-1/content"
        return httpx.Response(200, content=b"asset body")

    assert (
        main(
            ["asset", "content", "asset-1", "--output", str(output)],
            client=ApiClient(transport=httpx.MockTransport(handler)),
        )
        == 0
    )
    assert output.read_text(encoding="utf-8") == "asset body"
