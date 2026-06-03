from __future__ import annotations

import json

import httpx

from cli.__main__ import main
from cli.client import ApiClient


def test_runtime_provider_and_model_commands() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"ok": True})

    client = ApiClient(transport=httpx.MockTransport(handler))
    assert (
        main(
            [
                "runtime-provider",
                "list",
                "--org-id",
                "org-1",
                "--runtime-type",
                "opencode_local",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "runtime-provider",
                "create",
                "--org-id",
                "org-1",
                "--runtime-type",
                "opencode_local",
                "--provider-id",
                "deepseek",
                "--name",
                "DeepSeek",
                "--protocol",
                "openai_chat_completions",
                "--base-url",
                "http://localhost/v1",
                "--api-key",
                "secret",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "runtime-provider",
                "model-create",
                "--org-id",
                "org-1",
                "--runtime-type",
                "opencode_local",
                "--provider-id",
                "deepseek",
                "--model-id",
                "deepseek-v4-flash",
                "--display-name",
                "DeepSeek V4",
            ],
            client=client,
        )
        == 0
    )
    assert (
        main(
            [
                "runtime-provider",
                "model-delete",
                "--org-id",
                "org-1",
                "--runtime-type",
                "opencode_local",
                "--provider-id",
                "deepseek",
                "--model-id",
                "deepseek/deepseek-v4-flash",
            ],
            client=client,
        )
        == 0
    )

    assert requests[0].url.path == "/api/orgs/org-1/runtime-providers"
    assert requests[0].url.params["runtimeType"] == "opencode_local"
    assert requests[1].url.path == "/api/orgs/org-1/runtime-providers"
    assert json.loads(requests[1].read()) == {
        "runtimeType": "opencode_local",
        "providerId": "deepseek",
        "name": "DeepSeek",
        "protocol": "openai_chat_completions",
        "baseUrl": "http://localhost/v1",
        "apiKey": "secret",
    }
    assert requests[2].url.path == "/api/orgs/org-1/runtime-providers/deepseek/models"
    assert requests[2].url.params["runtimeType"] == "opencode_local"
    assert json.loads(requests[2].read()) == {
        "modelId": "deepseek-v4-flash",
        "displayName": "DeepSeek V4",
    }
    assert (
        "/api/orgs/org-1/runtime-providers/deepseek/models/"
        "deepseek%2Fdeepseek-v4-flash" in str(requests[3].url)
    )
    assert requests[3].url.params["runtimeType"] == "opencode_local"
