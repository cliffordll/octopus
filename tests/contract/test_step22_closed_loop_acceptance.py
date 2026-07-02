from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
import shutil
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Base
from packages.runtimes.types import RuntimeExecutionContext, RuntimeExecutionResult
from server.app import create_app


class ClosedLoopAdapter:
    type = "process"
    issue_id: str | None = None

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        await context.on_log("stdout", "closed-loop-start\n")
        issue_id = self.issue_id
        assert isinstance(issue_id, str)
        workspace_cwd = (context.env or {}).get("OCTOPUS_WORKSPACE_CWD")
        assert isinstance(workspace_cwd, str)
        output_dir = Path(workspace_cwd) / "artifacts" / "issues" / issue_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "ACCEPTANCE.md"
        output_path.write_text(
            "# Acceptance\n\nClosed loop output.\n", encoding="utf-8"
        )
        await context.on_log("stdout", "closed-loop-finished\n")
        return RuntimeExecutionResult(
            exit_code=0,
            result_json={"summary": "closed loop done"},
            work_products=[
                {
                    "type": "artifact",
                    "provider": "octopus",
                    "title": "Explicit output",
                    "summary": "structured runtime work product",
                    "content": "explicit output body",
                    "contentType": "text/plain",
                    "filename": "explicit-output.txt",
                }
            ],
        )


class FakeStorageService:
    provider = "fake"

    async def put_file(
        self,
        *,
        org_id: str,
        namespace: str,
        original_filename: str | None,
        content_type: str,
        body: bytes,
    ) -> dict[str, Any]:
        filename = original_filename or "object.bin"
        return {
            "provider": self.provider,
            "objectKey": f"{org_id}/{namespace}/{filename}",
            "contentType": content_type,
            "byteSize": len(body),
            "sha256": "fake-sha256",
            "originalFilename": original_filename,
        }


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, Path]]:
    root = Path("pytest-tmp") / f"step22-closed-loop-{uuid.uuid4().hex}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_STORAGE_DIR", str(root / "storage"))
    monkeypatch.setenv("OCTOPUS_RUN_LOG_DIR", str(root / "run-logs"))
    monkeypatch.setenv(
        "OCTOPUS_WORKSPACE_OPERATION_LOG_DIR", str(root / "operation-logs")
    )
    monkeypatch.setattr(
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: (root / "organizations" / org_id / "workspaces").resolve(),
    )
    monkeypatch.setattr(
        "server.services.workspaces.get_storage_service",
        lambda: FakeStorageService(),
    )
    import server.services.heartbeat as heartbeat_module

    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda runtime_type: ClosedLoopAdapter(),
    )

    async def closeout_signal_exists(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(
        heartbeat_module.HeartbeatService,
        "_run_has_issue_closeout_signal",
        closeout_signal_exists,
    )
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    try:
        yield application, root
    finally:
        await engine.dispose()
        shutil.rmtree(root, ignore_errors=True)


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body)
    return response.status_code, response.json()


async def _wait_for_dispatch(app: FastAPI) -> None:
    tasks = list(getattr(app.state, "heartbeat_dispatch_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


async def test_step22_closed_loop_acceptance_uses_public_api_and_service_boundaries(
    app: tuple[FastAPI, Path],
) -> None:
    application, _ = app

    org_code, org = await _request(
        application, "POST", "/api/orgs", json_body={"name": "Step 22 Acceptance"}
    )
    assert org_code == 200
    agent_code, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org['id']}/agents",
        json_body={
            "name": "Closed Loop Agent",
            "agentRuntimeType": "process",
            "agentRuntimeConfig": {"command": "closed-loop"},
        },
    )
    assert agent_code == 201
    project_code, project = await _request(
        application,
        "POST",
        f"/api/orgs/{org['id']}/projects",
        json_body={"name": "Closed Loop Project"},
    )
    assert project_code == 201
    issue_code, issue = await _request(
        application,
        "POST",
        f"/api/orgs/{org['id']}/issues",
        json_body={
            "title": "Produce closed loop output",
            "projectId": project["id"],
            "assigneeAgentId": agent["id"],
        },
    )
    assert issue_code == 200
    ClosedLoopAdapter.issue_id = issue["id"]

    execute_code, queued_run = await _request(
        application, "POST", f"/api/issues/{issue['id']}/execute"
    )
    assert execute_code == 202
    assert queued_run["status"] == "queued"
    await _wait_for_dispatch(application)

    run_code, run = await _request(
        application, "GET", f"/api/heartbeat-runs/{queued_run['id']}"
    )
    events_code, events = await _request(
        application, "GET", f"/api/heartbeat-runs/{queued_run['id']}/events"
    )
    log_code, run_log = await _request(
        application, "GET", f"/api/heartbeat-runs/{queued_run['id']}/log"
    )
    ops_code, operations = await _request(
        application,
        "GET",
        f"/api/heartbeat-runs/{queued_run['id']}/workspace-operations",
    )
    issue_detail_code, issue_detail = await _request(
        application, "GET", f"/api/issues/{issue['id']}"
    )

    assert run_code == 200
    assert run["status"] == "succeeded", {
        "error": run.get("error"),
        "errorCode": run.get("errorCode"),
    }
    assert run["resultJson"]["summary"] == "closed loop done"
    assert events_code == 200
    assert any(event["message"] == "closed-loop-start\n" for event in events)
    assert log_code == 200
    assert "closed-loop-finished" in run_log["content"]
    assert ops_code == 200
    adapter_operation = next(
        item for item in operations if item["metadata"].get("adapterExecution")
    )
    op_log_code, operation_log = await _request(
        application,
        "GET",
        f"/api/workspace-operations/{adapter_operation['id']}/log",
    )
    assert op_log_code == 200
    assert "closed-loop-start" in operation_log["content"]
    assert issue_detail_code == 200
    titles = {product["title"] for product in issue_detail["workProducts"]}
    assert {"Explicit output", "ACCEPTANCE.md"}.issubset(titles)
    assert all(product["contentPath"] for product in issue_detail["workProducts"])
