from __future__ import annotations

from packages.runtimes.openclaw_gateway.protocol import (
    build_agent_payload,
    build_connect_payload,
    resolve_auth,
    resolve_session_key,
    validate_gateway_url,
)
from packages.runtimes.openclaw_gateway.environment import (
    test_environment as run_environment_probe,
)


def test_openclaw_gateway_rejects_missing_and_non_websocket_urls() -> None:
    assert validate_gateway_url(None) == (
        False,
        "openclaw_gateway_url_missing",
        None,
    )
    assert validate_gateway_url("https://example.test/gateway") == (
        False,
        "openclaw_gateway_url_protocol_invalid",
        None,
    )


def test_openclaw_gateway_accepts_ws_and_wss_urls() -> None:
    assert validate_gateway_url("ws://localhost:8787/gateway") == (
        True,
        "openclaw_gateway_url_valid",
        None,
    )
    assert validate_gateway_url("wss://gateway.example.test/openclaw") == (
        True,
        "openclaw_gateway_url_valid",
        None,
    )


def test_openclaw_gateway_auth_derives_authorization_header_from_token() -> None:
    auth = resolve_auth({"authToken": "secret", "headers": {"X-Trace": "run-1"}})

    assert auth.present is True
    assert auth.token == "secret"
    assert auth.password is None
    assert auth.headers == {
        "X-Trace": "run-1",
        "Authorization": "Bearer secret",
    }


def test_openclaw_gateway_auth_preserves_explicit_authorization() -> None:
    auth = resolve_auth(
        {
            "token": "secret",
            "headers": {"Authorization": "Bearer explicit"},
        }
    )

    assert auth.present is True
    assert auth.token == "secret"
    assert auth.headers == {"Authorization": "Bearer explicit"}


def test_openclaw_gateway_session_key_strategies() -> None:
    assert (
        resolve_session_key(
            {"sessionKeyStrategy": "issue"}, run_id="run-1", issue_id="ISSUE-9"
        )
        == "octopus:issue:ISSUE-9"
    )
    assert (
        resolve_session_key(
            {"sessionKeyStrategy": "fixed", "sessionKey": "stable"},
            run_id="run-1",
            issue_id=None,
        )
        == "stable"
    )
    assert (
        resolve_session_key(
            {"sessionKeyStrategy": "run"}, run_id="run-1", issue_id=None
        )
        == "octopus:run:run-1"
    )


def test_openclaw_gateway_builds_connect_payload_with_defaults() -> None:
    payload = build_connect_payload(
        {"authToken": "secret"},
        request_id="msg-1",
    )

    assert payload["type"] == "req"
    assert payload["id"] == "msg-1"
    assert payload["method"] == "connect"
    assert payload["payload"]["protocol"] == 3
    assert payload["payload"]["client"]["id"] == "octopus-gateway-client"
    assert payload["payload"]["client"]["mode"] == "agent"
    assert payload["payload"]["role"] == "operator"
    assert payload["payload"]["scopes"] == ["operator.admin"]
    assert payload["payload"]["auth"]["token"] == "secret"


def test_openclaw_gateway_builds_agent_payload_from_runtime_context() -> None:
    payload = build_agent_payload(
        {
            "payloadTemplate": {"message": "wake now", "custom": {"a": 1}},
            "workspaceRuntime": {"services": [{"id": "preview"}]},
        },
        request_id="msg-2",
        run_id="run-123",
        agent_id="agent-123",
        org_id="org-123",
        agent_name="OpenClaw",
        task_message="Do the work",
        issue_id="ISSUE-123",
    )

    assert payload["type"] == "req"
    assert payload["id"] == "msg-2"
    assert payload["method"] == "agent"
    assert payload["payload"]["message"] == "wake now"
    assert payload["payload"]["custom"] == {"a": 1}
    assert payload["payload"]["idempotencyKey"] == "run-123"
    assert payload["payload"]["sessionKey"] == "octopus:issue:ISSUE-123"
    assert payload["payload"]["octopus"] == {
        "runId": "run-123",
        "agentId": "agent-123",
        "orgId": "org-123",
        "agentName": "OpenClaw",
        "issueId": "ISSUE-123",
    }
    assert payload["payload"]["workspaceRuntime"] == {"services": [{"id": "preview"}]}


async def test_openclaw_gateway_environment_reports_missing_url() -> None:
    result = await run_environment_probe({})

    assert result.agent_runtime_type == "openclaw_gateway"
    assert result.status == "failed"
    assert _check(result.checks, "url")["code"] == "openclaw_gateway_url_missing"
    assert _check(result.checks, "probe")["status"] == "skipped"


async def test_openclaw_gateway_environment_rejects_http_url() -> None:
    result = await run_environment_probe({"url": "https://example.test/gateway"})

    assert result.status == "failed"
    assert _check(result.checks, "url")["code"] == (
        "openclaw_gateway_url_protocol_invalid"
    )
    assert _check(result.checks, "probe")["status"] == "skipped"


async def test_openclaw_gateway_environment_warns_for_remote_plaintext_ws() -> None:
    result = await run_environment_probe(
        {"url": "ws://gateway.example.test/openclaw", "authToken": "secret"}
    )

    assert result.status == "warning"
    assert _check(result.checks, "url")["code"] == "openclaw_gateway_url_valid"
    assert _check(result.checks, "plaintext")["code"] == (
        "openclaw_gateway_plaintext_remote_ws"
    )
    assert _check(result.checks, "auth")["code"] == "openclaw_gateway_auth_present"
    assert _check(result.checks, "probe")["status"] == "skipped"


async def test_openclaw_gateway_environment_reports_auth_missing() -> None:
    result = await run_environment_probe({"url": "wss://gateway.example.test/openclaw"})

    assert result.status == "warning"
    assert _check(result.checks, "auth")["code"] == "openclaw_gateway_auth_missing"


async def test_openclaw_gateway_environment_uses_injected_probe() -> None:
    async def probe(url: str, config: dict) -> dict[str, str | None]:
        assert url == "wss://gateway.example.test/openclaw"
        assert config["authToken"] == "secret"
        return {
            "id": "probe",
            "label": "OpenClaw Gateway probe",
            "status": "ok",
            "code": "openclaw_gateway_probe_ok",
            "message": "OpenClaw Gateway probe completed.",
            "hint": None,
        }

    result = await run_environment_probe(
        {
            "url": "wss://gateway.example.test/openclaw",
            "authToken": "secret",
            "liveProbe": True,
        },
        probe=probe,
    )

    assert result.status == "ok"
    assert _check(result.checks, "probe")["code"] == "openclaw_gateway_probe_ok"


def _check(checks: list[dict], check_id: str) -> dict:
    return next(check for check in checks if check["id"] == check_id)
