from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
import json
import shutil
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import (
    Agent,
    Base,
    HeartbeatRun,
    HeartbeatRunEvent,
    Issue,
    Organization,
    WorkspaceOperation,
)
from server.app import create_app
from server.services.heartbeat import _run_log_dir


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker, Path]]:
    root = Path("pytest-tmp") / f"step20-{uuid.uuid4().hex}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_RUN_LOG_DIR", str(root / "run-logs"))
    monkeypatch.setenv(
        "OCTOPUS_WORKSPACE_OPERATION_LOG_DIR", str(root / "operation-logs")
    )
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    try:
        yield application, factory, root
    finally:
        await engine.dispose()
        shutil.rmtree(root, ignore_errors=True)


def test_default_run_log_dir_is_instance_scoped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OCTOPUS_RUN_LOG_DIR", raising=False)
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "octopus-home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "test-instance")

    assert (
        _run_log_dir()
        == (
            tmp_path
            / "octopus-home"
            / "instances"
            / "test-instance"
            / "data"
            / "run-logs"
        ).resolve()
    )


def test_run_log_dir_env_override_is_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "custom-run-logs"
    monkeypatch.setenv("OCTOPUS_RUN_LOG_DIR", str(override))
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "octopus-home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "test-instance")

    assert _run_log_dir() == override.resolve()


async def _request(
    app: FastAPI, method: str, path: str
) -> tuple[int, dict[str, str], Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path)
    return response.status_code, dict(response.headers), response.json()


async def _seed_observed_run(
    factory: async_sessionmaker, root: Path
) -> tuple[str, str, str, str]:
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    operation_id = str(uuid.uuid4())
    run_log_dir = root / "run-logs" / org_id
    operation_log_dir = root / "operation-logs" / org_id
    run_log_dir.mkdir(parents=True)
    operation_log_dir.mkdir(parents=True)
    run_log_ref = f"{org_id}/{run_id}.ndjson"
    operation_log_ref = f"{org_id}/{operation_id}.ndjson"
    (root / "run-logs" / run_log_ref).write_text(
        '{"stream":"stdout","chunk":"hello"}\n{"stream":"stderr","chunk":"warning"}\n',
        encoding="utf-8",
    )
    (root / "operation-logs" / operation_log_ref).write_text(
        '{"stream":"system","chunk":"provision"}\n',
        encoding="utf-8",
    )

    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"obs-{org_id[:8]}",
                name="Observed Org",
                issue_prefix="OBS",
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Observed Agent",
                agent_runtime_type="process",
                agent_runtime_config={"command": "python"},
                runtime_config={"env": "dev"},
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Observed issue",
                status="todo",
                priority="medium",
            )
        )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="on_demand",
                trigger_detail="manual",
                status="failed",
                error="adapter exploded",
                error_code="runtime_failed",
                exit_code=1,
                result_json={"summary": "failed"},
                stdout_excerpt="hello",
                stderr_excerpt="warning",
                log_store="local_file",
                log_ref=run_log_ref,
                log_bytes=72,
                context_snapshot={"issueId": issue_id, "agentRuntimeType": "process"},
            )
        )
        session.add(
            HeartbeatRunEvent(
                org_id=org_id,
                run_id=run_id,
                agent_id=agent_id,
                seq=1,
                event_type="heartbeat.run.event",
                stream="stderr",
                level="error",
                message="warning",
                payload={"phase": "adapter"},
            )
        )
        session.add(
            WorkspaceOperation(
                id=operation_id,
                org_id=org_id,
                heartbeat_run_id=run_id,
                phase="workspace_provision",
                command="python -V",
                status="failed",
                exit_code=1,
                log_store="local_file",
                log_ref=operation_log_ref,
                log_bytes=40,
                stdout_excerpt=None,
                stderr_excerpt="warning",
                metadata_json={"adapterExecution": True},
            )
        )
        await session.commit()
    return org_id, agent_id, issue_id, run_id


async def test_step20_upstream_observability_paths_are_exposed() -> None:
    from packages.shared.api_paths import heartbeat
    from packages.shared.api_paths import run_intelligence
    from packages.shared.api_paths import workspace_operations

    assert heartbeat.HEARTBEAT_RUN_LOG_PATH == "/api/heartbeat-runs/{runId}/log"
    assert heartbeat.HEARTBEAT_RUN_STREAM_PATH == "/api/heartbeat-runs/{runId}/stream"
    assert heartbeat.ISSUE_HEARTBEAT_RUNS_PATH == "/api/issues/{issueId}/heartbeat-runs"
    assert (
        heartbeat.HEARTBEAT_RUN_WORKSPACE_OPERATIONS_PATH
        == "/api/heartbeat-runs/{runId}/workspace-operations"
    )
    assert (
        workspace_operations.WORKSPACE_OPERATION_LOG_PATH
        == "/api/workspace-operations/{operationId}/log"
    )
    assert (
        run_intelligence.RUN_INTELLIGENCE_ORG_RUNS_PATH
        == "/api/run-intelligence/orgs/{orgId}/runs"
    )
    assert (
        run_intelligence.RUN_INTELLIGENCE_RUN_PATH
        == "/api/run-intelligence/runs/{runId}"
    )


async def test_heartbeat_run_log_and_workspace_operation_routes(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, root = app
    _, _, _, run_id = await _seed_observed_run(factory, root)

    log_code, log_headers, log_body = await _request(
        application, "GET", f"/api/heartbeat-runs/{run_id}/log?offset=0&limitBytes=32"
    )
    ops_code, _, operations = await _request(
        application, "GET", f"/api/heartbeat-runs/{run_id}/workspace-operations"
    )
    assert isinstance(operations, list)
    operation_id = operations[0]["id"]
    op_log_code, op_log_headers, op_log_body = await _request(
        application,
        "GET",
        f"/api/workspace-operations/{operation_id}/log?offset=0&limitBytes=256000",
    )

    assert log_code == 200
    assert log_headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert log_body["content"].startswith('{"stream":"stdout"')
    assert log_body["endOffset"] == 32
    assert log_body["eof"] is False
    assert log_body["nextOffset"] == 32
    assert ops_code == 200
    assert operations[0]["phase"] == "workspace_provision"
    assert operations[0]["stderrExcerpt"] == "warning"
    assert op_log_code == 200
    assert op_log_headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert "provision" in op_log_body["content"]
    assert op_log_body["eof"] is True


async def test_heartbeat_run_stream_returns_incremental_ndjson(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, root = app
    _, _, _, run_id = await _seed_observed_run(factory, root)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/heartbeat-runs/{run_id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["run", "event", "log", "final"]
    assert events[0]["run"]["id"] == run_id
    assert events[1]["event"]["seq"] == 1
    assert events[2]["content"].startswith('{"stream":"stdout"')
    assert events[2]["nextOffset"] > 0
    assert events[3]["run"]["status"] == "failed"


async def test_issue_heartbeat_runs_route_returns_task_execution_summary(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, root = app
    org_id, agent_id, issue_id, run_id = await _seed_observed_run(factory, root)

    code, _, runs = await _request(
        application, "GET", f"/api/issues/{issue_id}/heartbeat-runs"
    )
    detail_code, _, detail = await _request(
        application, "GET", f"/api/heartbeat-runs/{run_id}"
    )

    assert code == 200
    assert len(runs) == 1
    assert runs[0]["runId"] == run_id
    assert runs[0]["status"] == "failed"
    assert runs[0]["agentId"] == agent_id
    assert runs[0]["issueId"] == issue_id
    assert runs[0]["issueIdentifier"] is None
    assert runs[0]["issueTitle"] == "Observed issue"
    assert runs[0]["summary"] == "failed"
    assert runs[0]["error"] == "adapter exploded"

    assert detail_code == 200
    assert detail["id"] == run_id
    assert detail["issueId"] == issue_id
    assert detail["issueTitle"] == "Observed issue"
    assert detail["issueIdentifier"] is None
    assert detail["projectId"] is None
    assert detail["goalId"] is None
    assert detail["contextSnapshot"]["issueId"] == issue_id


async def test_run_intelligence_routes_return_upstream_observed_run_shape(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, root = app
    org_id, agent_id, issue_id, run_id = await _seed_observed_run(factory, root)

    list_code, _, rows = await _request(
        application,
        "GET",
        f"/api/run-intelligence/orgs/{org_id}/runs?status=failed&runtime=process&issueId={issue_id}",
    )
    detail_code, _, detail = await _request(
        application, "GET", f"/api/run-intelligence/runs/{run_id}"
    )
    events_code, _, events = await _request(
        application, "GET", f"/api/run-intelligence/runs/{run_id}/events"
    )
    log_code, _, log = await _request(
        application, "GET", f"/api/run-intelligence/runs/{run_id}/log"
    )

    assert list_code == 200
    assert len(rows) == 1
    assert rows[0]["run"]["id"] == run_id
    assert rows[0]["agentName"] == "Observed Agent"
    assert rows[0]["issue"]["id"] == issue_id
    assert rows[0]["bundle"]["agentRuntimeType"] == "process"
    assert detail_code == 200
    assert detail["run"]["stderrExcerpt"] == "warning"
    assert detail["run"]["agentId"] == agent_id
    assert events_code == 200
    assert events[0]["message"] == "warning"
    assert log_code == 200
    assert "warning" in log["content"]
