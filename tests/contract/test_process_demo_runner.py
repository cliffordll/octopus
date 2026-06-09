from __future__ import annotations

import sys
import json

import pytest

from packages.runtimes.process.demo import main
from packages.runtimes.process.runner import execute
from packages.runtimes.types import RuntimeExecutionContext


def test_process_demo_runner_prints_safe_demo_payload(capsys) -> None:
    assert main() == 0

    output = capsys.readouterr().out
    payload = json.loads(output)

    assert payload["message"] == "Octopus process runtime demo succeeded."
    assert isinstance(payload["timestamp"], str)
    assert isinstance(payload["cwd"], str)
    assert payload["safeEnv"] == {}


@pytest.mark.asyncio
async def test_process_runtime_executes_demo_module() -> None:
    logs: list[tuple[str, str]] = []

    async def on_log(stream: str, message: str) -> None:
        logs.append((stream, message))

    result = await execute(
        RuntimeExecutionContext(
            run_id="run-demo",
            agent_id="agent-demo",
            org_id="org-demo",
            agent_name="Demo Agent",
            config={
                "command": sys.executable,
                "args": ["-m", "packages.runtimes.process.demo"],
                "timeoutSec": 10,
            },
            on_log=on_log,
        )
    )

    assert result.exit_code == 0
    assert result.error_message is None
    assert result.result_json is not None
    stdout = result.result_json["stdout"]
    payload = json.loads(stdout)
    assert payload["message"] == "Octopus process runtime demo succeeded."
    assert ("stdout", stdout) in logs
