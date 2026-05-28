from __future__ import annotations

import json
import sys
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from packages.database.clients import (
    async_transaction,
    create_database_engine,
    create_session_factory,
)
from packages.database.schema import Base, Organization
from packages.runtimes.claude_local import ClaudeLocalRuntimeAdapter
from packages.runtimes.opencode_local import OpenCodeLocalRuntimeAdapter
from packages.runtimes.types import RuntimeExecutionContext
from packages.shared.constants.agent import AgentRuntimeType
from packages.shared.types.agent import CreateAgentPayload
from server.services.agents import AgentService
from server.services.heartbeat import HeartbeatService


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    async with factory() as active_session:
        yield active_session
    await engine.dispose()


@pytest.fixture
def http_endpoint() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body.decode() or "{}")
            response = json.dumps(
                {"receivedRunId": payload["runId"], "agentName": payload["agentName"]}
            ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/invoke"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


async def _seed_agent(
    session: AsyncSession,
    *,
    name: str,
    runtime_type: str,
    runtime_config: dict[str, Any],
) -> dict[str, Any]:
    org = Organization(url_key=name.lower(), name=name, issue_prefix="RTA")
    service = AgentService(session)
    async with async_transaction(session):
        session.add(org)
        await session.flush()
        payload = cast(
            CreateAgentPayload,
            {
                "name": name,
                "agentRuntimeType": cast(AgentRuntimeType, runtime_type),
                "agentRuntimeConfig": runtime_config,
            },
        )
        agent = await service.create_agent(
            org.id,
            payload,
            actor_type="board",
            actor_id="local-board",
        )
        return cast(dict[str, Any], agent)


async def test_http_runtime_executes_through_heartbeat_run(
    session: AsyncSession, http_endpoint: str
) -> None:
    agent = await _seed_agent(
        session,
        name="HttpRuntime",
        runtime_type="http",
        runtime_config={"url": http_endpoint, "payloadTemplate": {"source": "test"}},
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = await heartbeat.wakeup(
            agent["id"], {}, actor_type="board", actor_id="local-board"
        )

    assert run is not None
    assert run["status"] == "succeeded"
    result = run["resultJson"]
    assert result is not None
    assert result["statusCode"] == 200
    assert result["body"]["receivedRunId"] == run["id"]


@pytest.mark.parametrize("runtime_type", ["claude_local", "opencode_local"])
async def test_local_cli_runtimes_reuse_process_execution_contract(
    session: AsyncSession, runtime_type: str
) -> None:
    agent = await _seed_agent(
        session,
        name=f"{runtime_type}Runtime",
        runtime_type=runtime_type,
        runtime_config={
            "command": sys.executable,
            "args": ["-c", "print('local-cli-ok')"],
        },
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = await heartbeat.wakeup(
            agent["id"], {}, actor_type="board", actor_id="local-board"
        )

    assert run is not None
    assert run["status"] == "succeeded"
    result = run["resultJson"]
    assert result is not None
    assert "local-cli-ok" in result["stdout"]
    assert isinstance(run["processPid"], int)


async def test_claude_local_executes_stream_json_and_normalizes_result(
    tmp_path,
) -> None:
    capture_path = tmp_path / "claude-capture.json"
    fake_claude = tmp_path / "fake_claude.py"
    fake_claude.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "prompt = sys.stdin.read()",
                "with open(os.environ['OCTOPUS_TEST_CAPTURE'], 'w', encoding='utf-8') as fh:",
                "    json.dump({'argv': sys.argv[1:], 'prompt': prompt}, fh)",
                "print(json.dumps({'type':'system','subtype':'init','session_id':'claude-session-1','model':'claude-test'}))",
                "print(json.dumps({'type':'assistant','session_id':'claude-session-1','message':{'content':[{'type':'text','text':'hello from claude'}]}}))",
                "print(json.dumps({'type':'result','subtype':'success','session_id':'claude-session-1','result':'done','usage':{'input_tokens':3,'cache_read_input_tokens':1,'cache_creation_input_tokens':2,'output_tokens':5},'total_cost_usd':0.02}))",
            ]
        ),
        encoding="utf-8",
    )
    logs: list[tuple[str, str]] = []

    async def on_log(stream: str, chunk: str) -> None:
        logs.append((stream, chunk))

    async def on_process_started(_pid: int, _started_at) -> None:
        return None

    adapter = ClaudeLocalRuntimeAdapter()
    result = await adapter.execute(
        RuntimeExecutionContext(
            run_id="run-claude",
            agent_id="agent-claude",
            org_id="org-claude",
            agent_name="Claude Agent",
            config={
                "command": sys.executable,
                "args": [str(fake_claude)],
                "model": "claude-test-model",
                "effort": "high",
                "maxTurnsPerRun": 4,
                "env": {"OCTOPUS_TEST_CAPTURE": str(capture_path)},
                "promptTemplate": "Respond from Claude.",
            },
            on_log=on_log,
            on_process_started=on_process_started,
        )
    )

    capture = json.loads(capture_path.read_text(encoding="utf-8"))

    assert "--print" in capture["argv"]
    assert "-" in capture["argv"]
    assert (
        capture["argv"][capture["argv"].index("--output-format") + 1] == "stream-json"
    )
    assert "--verbose" in capture["argv"]
    assert capture["argv"][capture["argv"].index("--model") + 1] == "claude-test-model"
    assert capture["prompt"] == "Respond from Claude."
    assert result.exit_code == 0
    assert result.session_id_after == "claude-session-1"
    assert result.usage_json == {
        "inputTokens": 3,
        "cachedInputTokens": 3,
        "outputTokens": 5,
    }
    assert result.result_json is not None
    assert result.result_json["summary"] == "done"
    assert result.result_json["model"] == "claude-test"
    assert result.result_json["costUsd"] == 0.02
    assert any(stream == "stdout" for stream, _ in logs)


async def test_claude_local_mounts_desired_skills_with_add_dir(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    review_skill = skills_root / "review"
    review_skill.mkdir(parents=True)
    review_skill.joinpath("SKILL.md").write_text(
        "# Review\n\nReview code changes.", encoding="utf-8"
    )
    capture_path = tmp_path / "claude-skills-capture.json"
    fake_claude = tmp_path / "fake_claude.py"
    fake_claude.write_text(
        "\n".join(
            [
                "import json, os, pathlib, sys",
                "argv = sys.argv[1:]",
                "add_dir = argv[argv.index('--add-dir') + 1]",
                "skill_file = pathlib.Path(add_dir) / '.claude' / 'skills' / 'review' / 'SKILL.md'",
                "with open(os.environ['OCTOPUS_TEST_CAPTURE'], 'w', encoding='utf-8') as fh:",
                "    json.dump({'argv': argv, 'skillText': skill_file.read_text(encoding='utf-8')}, fh)",
                "print(json.dumps({'type':'result','subtype':'success','session_id':'claude-session','result':'done','usage':{}}))",
            ]
        ),
        encoding="utf-8",
    )

    adapter = ClaudeLocalRuntimeAdapter()
    result = await adapter.execute(
        RuntimeExecutionContext(
            run_id="run-claude-skills",
            agent_id="agent-claude",
            org_id="org-claude",
            agent_name="Claude Agent",
            config={
                "command": sys.executable,
                "args": [str(fake_claude)],
                "skillsRootPath": str(skills_root),
                "_octopus": {"desiredSkills": ["review"]},
                "env": {"OCTOPUS_TEST_CAPTURE": str(capture_path)},
            },
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    assert "--add-dir" in capture["argv"]
    assert capture["skillText"] == "# Review\n\nReview code changes."
    assert result.result_json is not None
    assert result.result_json["loadedSkills"] == [
        {
            "key": "review",
            "runtimeName": "review",
            "name": "review",
            "description": "Review code changes.",
        }
    ]


async def test_opencode_local_executes_jsonl_and_normalizes_result(tmp_path) -> None:
    capture_path = tmp_path / "opencode-capture.json"
    fake_opencode = tmp_path / "fake_opencode.py"
    fake_opencode.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "prompt = sys.stdin.read()",
                "with open(os.environ['OCTOPUS_TEST_CAPTURE'], 'w', encoding='utf-8') as fh:",
                "    json.dump({'argv': sys.argv[1:], 'prompt': prompt}, fh)",
                "print(json.dumps({'type':'step_start','sessionID':'ses_123'}))",
                "print(json.dumps({'type':'text','part':{'type':'text','text':'hello from opencode'}}))",
                "print(json.dumps({'type':'step_finish','part':{'reason':'stop','cost':0.003,'tokens':{'input':7,'output':11,'reasoning':2,'cache':{'read':5,'write':0}}}}))",
            ]
        ),
        encoding="utf-8",
    )
    logs: list[tuple[str, str]] = []

    async def on_log(stream: str, chunk: str) -> None:
        logs.append((stream, chunk))

    adapter = OpenCodeLocalRuntimeAdapter()
    result = await adapter.execute(
        RuntimeExecutionContext(
            run_id="run-opencode",
            agent_id="agent-opencode",
            org_id="org-opencode",
            agent_name="OpenCode Agent",
            config={
                "command": sys.executable,
                "args": [str(fake_opencode)],
                "model": "openai/gpt-5",
                "variant": "default",
                "env": {"OCTOPUS_TEST_CAPTURE": str(capture_path)},
                "promptTemplate": "Respond from OpenCode.",
            },
            on_log=on_log,
        )
    )

    capture = json.loads(capture_path.read_text(encoding="utf-8"))

    assert capture["argv"][:2] == ["run", "--format"]
    assert capture["argv"][capture["argv"].index("--format") + 1] == "json"
    assert capture["argv"][capture["argv"].index("--model") + 1] == "openai/gpt-5"
    assert capture["argv"][capture["argv"].index("--variant") + 1] == "default"
    assert capture["prompt"] == "Respond from OpenCode."
    assert result.exit_code == 0
    assert result.session_id_after == "ses_123"
    assert result.usage_json == {
        "inputTokens": 7,
        "cachedInputTokens": 5,
        "outputTokens": 13,
    }
    assert result.result_json is not None
    assert result.result_json["summary"] == "hello from opencode"
    assert result.result_json["costUsd"] == 0.003
    assert result.result_json["provider"] == "openai"
    assert any(stream == "stdout" for stream, _ in logs)


async def test_opencode_local_injects_desired_skills_into_managed_home(
    tmp_path,
) -> None:
    skills_root = tmp_path / "skills"
    review_skill = skills_root / "review"
    review_skill.mkdir(parents=True)
    review_skill.joinpath("SKILL.md").write_text(
        "# Review\n\nReview code changes.", encoding="utf-8"
    )
    capture_path = tmp_path / "opencode-skills-capture.json"
    fake_opencode = tmp_path / "fake_opencode.py"
    fake_opencode.write_text(
        "\n".join(
            [
                "import json, os, pathlib, sys",
                "skill_file = pathlib.Path(os.environ['HOME']) / '.claude' / 'skills' / 'review' / 'SKILL.md'",
                "with open(os.environ['OCTOPUS_TEST_CAPTURE'], 'w', encoding='utf-8') as fh:",
                "    json.dump({'home': os.environ['HOME'], 'skillText': skill_file.read_text(encoding='utf-8')}, fh)",
                "print(json.dumps({'type':'step_start','sessionID':'opencode-session'}))",
            ]
        ),
        encoding="utf-8",
    )

    adapter = OpenCodeLocalRuntimeAdapter()
    result = await adapter.execute(
        RuntimeExecutionContext(
            run_id="run-opencode-skills",
            agent_id="agent-opencode",
            org_id="org-opencode",
            agent_name="OpenCode Agent",
            config={
                "command": sys.executable,
                "args": [str(fake_opencode)],
                "skillsRootPath": str(skills_root),
                "_octopus": {"desiredSkills": ["review"]},
                "env": {"OCTOPUS_TEST_CAPTURE": str(capture_path)},
            },
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    normalized_home = capture["home"].replace("\\", "/")
    assert normalized_home.endswith(
        ".octopus/runtime-homes/opencode_local/org-opencode/agent-opencode/home"
    )
    assert capture["skillText"] == "# Review\n\nReview code changes."
    assert result.result_json is not None
    assert result.result_json["loadedSkills"] == [
        {
            "key": "review",
            "runtimeName": "review",
            "name": "review",
            "description": "Review code changes.",
        }
    ]


async def _noop_log(stream: str, chunk: str) -> None:
    return None
