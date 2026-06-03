from __future__ import annotations

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_heartbeat_workspace_operation_log_command() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/workspace-operations/operation-1/log"
        assert request.url.params["offset"] == "5"
        assert request.url.params["limitBytes"] == "1000"
        return httpx.Response(200, json={"text": "full log", "eof": True})

    assert (
        main(
            [
                "heartbeat",
                "workspace-operation-log",
                "operation-1",
                "--offset",
                "5",
                "--limit-bytes",
                "1000",
            ],
            client=ApiClient(transport=httpx.MockTransport(handler)),
        )
        == 0
    )
