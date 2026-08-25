from __future__ import annotations

import httpx
import pytest

from cli.client import ApiClient, ApiError


def test_client_sends_requests_to_configured_base_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://example.test/api/orgs")
        return httpx.Response(200, json=[{"id": "org-1"}])

    client = ApiClient("http://example.test", transport=httpx.MockTransport(handler))

    assert client.request("GET", "/api/orgs") == [{"id": "org-1"}]


def test_client_reports_api_detail() -> None:
    client = ApiClient(
        "http://example.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403, json={"detail": "Board access required"}
            )
        ),
    )

    with pytest.raises(ApiError, match="Board access required") as raised:
        client.request("POST", "/api/approvals/a-1/approve", json={})

    assert raised.value.status_code == 403


@pytest.mark.parametrize(
    ("api_base", "expected_trust_env"),
    [
        ("http://127.0.0.1:8000", False),
        ("http://localhost:8000/api", False),
        ("http://[::1]:8000", False),
        ("https://octopus.example.test", True),
    ],
)
def test_client_bypasses_environment_proxy_only_for_loopback(
    monkeypatch: pytest.MonkeyPatch,
    api_base: str,
    expected_trust_env: bool,
) -> None:
    captured: dict[str, object] = {}

    class CapturingClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("cli.client.httpx.Client", CapturingClient)
    ApiClient(api_base)
    assert captured["trust_env"] is expected_trust_env
