from __future__ import annotations

from pathlib import Path
from typing import Any
import sys

import httpx
import pytest

from packages.runtimes.claude_local.runner import execute as execute_claude_local
from packages.runtimes.codex_local.runner import execute as execute_codex_local
from packages.runtimes.http.environment import (
    test_environment as _test_http_environment,
)
from packages.runtimes.opencode_local.environment import (
    test_environment as _test_opencode_environment,
)
from packages.runtimes.types import RuntimeExecutionContext


async def _noop_on_log(stream: str, chunk: str) -> None:
    return None


async def test_http_live_probe_reports_timeout_and_server_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimeoutClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> TimeoutClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, method: str, url: str) -> httpx.Response:
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(
        "packages.runtimes.environment.httpx.AsyncClient", TimeoutClient
    )

    timed_out = await _test_http_environment(
        {
            "url": "https://runtime.test/health",
            "liveProbe": True,
            "probeTimeoutSec": 0.01,
        }
    )

    assert timed_out.status == "failed"
    checks = {check["id"]: check for check in timed_out.checks}
    assert checks["liveProbe"]["status"] == "failed"
    assert "timed out" in checks["liveProbe"]["message"]

    class FailingClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> FailingClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def request(self, method: str, url: str) -> httpx.Response:
            return httpx.Response(503)

    monkeypatch.setattr(
        "packages.runtimes.environment.httpx.AsyncClient", FailingClient
    )

    failed = await _test_http_environment(
        {"url": "https://runtime.test/health", "liveProbe": True}
    )

    failed_checks = {check["id"]: check for check in failed.checks}
    assert failed.status == "failed"
    assert failed_checks["liveProbe"]["message"] == "HTTP live probe returned 503."


async def test_cli_hello_probe_failure_is_visible(tmp_path: Path) -> None:
    script = tmp_path / "failing_probe.py"
    script.write_text(
        "import sys\nprint('probe failed')\nsys.exit(7)\n", encoding="utf-8"
    )

    result = await _test_opencode_environment(
        {
            "cwd": str(tmp_path),
            "command": sys.executable,
            "model": "openai/gpt-5",
            "liveProbe": True,
            "probeArgs": [str(script)],
        }
    )

    checks = {check["id"]: check for check in result.checks}
    assert result.status == "failed"
    assert checks["helloProbe"]["status"] == "failed"
    assert "exited with code 7" in checks["helloProbe"]["message"]


async def test_opencode_live_probe_checks_configured_model_availability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = tmp_path / "ok_probe.py"
    script.write_text("print('ok')\n", encoding="utf-8")

    async def fake_list_models(config: dict[str, Any]) -> list[dict[str, str]]:
        return [{"id": "openai/gpt-5", "label": "GPT-5"}]

    monkeypatch.setattr(
        "packages.runtimes.opencode_local.environment.list_models", fake_list_models
    )

    available = await _test_opencode_environment(
        {
            "cwd": str(tmp_path),
            "command": sys.executable,
            "model": "openai/gpt-5",
            "liveProbe": True,
            "probeArgs": [str(script)],
        }
    )
    missing = await _test_opencode_environment(
        {
            "cwd": str(tmp_path),
            "command": sys.executable,
            "model": "anthropic/claude-sonnet",
            "liveProbe": True,
            "probeArgs": [str(script)],
        }
    )

    available_checks = {check["id"]: check for check in available.checks}
    missing_checks = {check["id"]: check for check in missing.checks}
    assert available_checks["availableModel"]["status"] == "ok"
    assert missing.status == "failed"
    assert missing_checks["availableModel"]["status"] == "failed"


async def test_claude_resume_unknown_session_retries_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_args: list[tuple[str, ...]] = []
    logs: list[tuple[str, str]] = []

    class FakeProcess:
        def __init__(self, returncode: int, stdout: bytes, stderr: bytes) -> None:
            self.returncode = returncode
            self._stdout = stdout
            self._stderr = stderr

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return self._stdout, self._stderr

        def kill(self) -> None:
            raise AssertionError("process should not be killed")

    async def fake_create_subprocess_exec(*args: str, **kwargs: Any) -> FakeProcess:
        captured_args.append(args)
        if len(captured_args) == 1:
            return FakeProcess(1, b"", b"Error: unknown session old-session\n")
        return FakeProcess(
            0,
            b'{"type":"result","subtype":"success","session_id":"new-session","result":"ok","usage":{}}\n',
            b"",
        )

    async def on_log(stream: str, chunk: str) -> None:
        logs.append((stream, chunk))

    monkeypatch.setattr(
        "packages.runtimes.claude_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await execute_claude_local(
        RuntimeExecutionContext(
            run_id="run-26",
            agent_id="agent-26",
            org_id="org-26",
            agent_name="Claude",
            config={
                "command": "claude-test",
                "_octopus": {"sessionIdBefore": "old-session"},
            },
            on_log=on_log,
        )
    )

    assert "--resume" in captured_args[0]
    assert "old-session" in captured_args[0]
    assert "--resume" not in captured_args[1]
    assert result.exit_code == 0
    assert result.session_id_after == "new-session"
    assert any("retrying with a fresh session" in chunk for _, chunk in logs)


async def test_codex_cwd_mismatch_skips_resume_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    previous_cwd = tmp_path / "previous"
    current_cwd = tmp_path / "current"
    previous_cwd.mkdir()
    current_cwd.mkdir()
    captured_args: list[tuple[str, ...]] = []
    logs: list[tuple[str, str]] = []

    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return (
                b'{"type":"thread.started","thread_id":"fresh-thread"}\n'
                b'{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n',
                b"",
            )

        def kill(self) -> None:
            raise AssertionError("process should not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured_args.append(args)
        return FakeCodexProcess()

    async def on_log(stream: str, chunk: str) -> None:
        logs.append((stream, chunk))

    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-26",
            agent_id="agent-26",
            org_id="org-26",
            agent_name="Codex",
            config={
                "command": "codex-test",
                "cwd": str(current_cwd),
                "_octopus": {
                    "sessionIdBefore": "old-thread",
                    "sessionCwd": str(previous_cwd),
                },
            },
            on_log=on_log,
        )
    )

    assert "resume" not in captured_args[0]
    assert result.session_id_after == "fresh-thread"
    assert any("workspace mismatch" in chunk for _, chunk in logs)
