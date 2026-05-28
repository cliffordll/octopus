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
