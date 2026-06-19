from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from fastapi.testclient import TestClient
from starlette.responses import Response

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import (
    ActivityLog,
    Agent,
    Base,
    HeartbeatRun,
    Organization,
)
from server.app import create_app
from server.services.heartbeat import HeartbeatService


def test_step13_run_recovery_contract_exposes_upstream_paths_and_limits() -> None:
    paths = importlib.import_module("packages.shared.api_paths.heartbeat")
    constants = importlib.import_module("packages.shared.constants.heartbeat")

    assert paths.HEARTBEAT_RUN_CANCEL_PATH == "/api/heartbeat-runs/{runId}/cancel"
    assert paths.HEARTBEAT_RUN_RETRY_PATH == "/api/heartbeat-runs/{runId}/retry"
    assert constants.AGENT_RUN_CONCURRENCY_DEFAULT == 3
    assert constants.AGENT_RUN_CONCURRENCY_MIN == 1
    assert constants.AGENT_RUN_CONCURRENCY_MAX == 10


async def test_instance_scheduler_heartbeats_lists_timer_policy(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key="timer-policy",
                name="Timer Policy",
                issue_prefix="TP",
            )
        )
        session.add_all(
            [
                Agent(
                    id="agent-scheduled",
                    org_id=org_id,
                    name="Scheduled Agent",
                    role="engineer",
                    title="Builder",
                    status="idle",
                    agent_runtime_type="codex_local",
                    runtime_config={
                        "heartbeat": {
                            "enabled": True,
                            "intervalSec": 60,
                            "wakeOnDemand": False,
                        }
                    },
                ),
                Agent(
                    id="agent-inactive",
                    org_id=org_id,
                    name="Inactive Agent",
                    role="qa",
                    status="idle",
                    agent_runtime_type="codex_local",
                    runtime_config={"heartbeat": {"enabled": True, "intervalSec": 0}},
                ),
                Agent(
                    id="agent-paused",
                    org_id=org_id,
                    name="Paused Agent",
                    role="engineer",
                    status="paused",
                    agent_runtime_type="codex_local",
                    runtime_config={"heartbeat": {"enabled": True, "intervalSec": 60}},
                ),
            ]
        )
        await session.commit()

    code, body = await _request(
        application, "GET", "/api/instance/scheduler-heartbeats"
    )

    assert code == 200
    assert [item["id"] for item in body] == ["agent-inactive", "agent-scheduled"]
    assert body[0]["heartbeatEnabled"] is True
    assert body[0]["intervalSec"] == 300.0
    assert body[0]["schedulerActive"] is True
    assert body[1] == {
        "id": "agent-scheduled",
        "orgId": org_id,
        "organizationName": "Timer Policy",
        "organizationIssuePrefix": "TP",
        "agentName": "Scheduled Agent",
        "agentUrlKey": "scheduled-agent",
        "role": "engineer",
        "title": "Builder",
        "status": "idle",
        "agentRuntimeType": "codex_local",
        "intervalSec": 60.0,
        "heartbeatEnabled": True,
        "schedulerActive": True,
        "lastHeartbeatAt": None,
    }


def test_step13_events_contract_accepts_incremental_query_window() -> None:
    parameters = inspect.signature(HeartbeatService.list_events).parameters

    assert parameters["after_seq"].default == 0
    assert parameters["limit"].default == 200


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    active = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with active.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield active
    finally:
        await active.dispose()


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine
) -> tuple[FastAPI, async_sessionmaker]:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory

    @application.middleware("http")
    async def retain_actor(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        return await call_next(request)

    return application, factory


async def _request(
    app: FastAPI, method: str, path: str, *, json: dict[str, Any] | None = None
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json)
    return response.status_code, response.json()


async def test_cancel_retry_and_incremental_events_routes(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id, url_key="step13-api", name="Step 13", issue_prefix="RUN"
            )
        )
        await session.commit()
    _, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Recover Route",
            "agentRuntimeConfig": {
                "command": sys.executable,
                "args": ["-c", "print('retry-ok')"],
            },
        },
    )
    async with factory() as session:
        queued = HeartbeatRun(
            org_id=org_id,
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="queued",
        )
        session.add(queued)
        await session.commit()
        queued_id = queued.id

    cancel_code, cancelled = await _request(
        application, "POST", f"/api/heartbeat-runs/{queued_id}/cancel", json={}
    )
    events_code, events = await _request(
        application,
        "GET",
        f"/api/heartbeat-runs/{queued_id}/events?afterSeq=0&limit=1",
    )
    retry_code, retried = await _request(
        application, "POST", f"/api/heartbeat-runs/{queued_id}/retry", json={}
    )
    tasks = list(getattr(application.state, "heartbeat_dispatch_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)

    assert cancel_code == 200 and cancelled["status"] == "cancelled"
    assert events_code == 200 and len(events) == 1
    assert events[0]["message"] == "run cancelled"
    assert retry_code == 200 and retried["retryOfRunId"] == queued_id
    async with factory() as session:
        actions = (await session.execute(select(ActivityLog.action))).scalars().all()
    assert "heartbeat.cancelled" in actions
    assert "heartbeat.retried" in actions


async def test_cancel_interrupts_active_process_run(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    engine = create_database_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'step13-live-cancel.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    org_id = str(uuid.uuid4())
    try:
        async with factory() as session:
            session.add(
                Organization(
                    id=org_id,
                    url_key="step13-live",
                    name="Step 13 Live",
                    issue_prefix="RUN",
                )
            )
            await session.commit()
        _, agent = await _request(
            application,
            "POST",
            f"/api/orgs/{org_id}/agents",
            json={
                "name": "Live Runner",
                "agentRuntimeConfig": {
                    "command": sys.executable,
                    "args": ["-c", "import time; time.sleep(10)"],
                },
            },
        )
        invocation = asyncio.create_task(
            _request(application, "POST", f"/api/agents/{agent['id']}/wakeup", json={})
        )
        run_id: str | None = None
        observed_statuses: list[str] = []
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            async with factory() as session:
                rows = (
                    (
                        await session.execute(
                            select(HeartbeatRun).where(
                                HeartbeatRun.agent_id == agent["id"]
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            observed_statuses = [row.status for row in rows]
            row = next((row for row in rows if row.status == "running"), None)
            if row is not None:
                run_id = row.id
                break
            await asyncio.sleep(0.02)

        assert run_id is not None, observed_statuses
        cancel_code, cancelled = await _request(
            application, "POST", f"/api/heartbeat-runs/{run_id}/cancel", json={}
        )
        await invocation
        detail_code = 0
        detail: dict[str, Any] = {}
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            detail_code, detail = await _request(
                application, "GET", f"/api/heartbeat-runs/{run_id}"
            )
            if detail_code == 200 and detail["status"] == "cancelled":
                break
            await asyncio.sleep(0.02)

        assert cancel_code == 200 and cancelled["status"] == "cancelled"
        assert detail_code == 200 and detail["status"] == "cancelled"
    finally:
        await engine.dispose()


def test_lifespan_scheduler_executes_timer_wakeup(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "step13-scheduler.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OCTOPUS_AUTO_MIGRATE", "1")
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_HEARTBEAT_SCHEDULER_INTERVAL_SECONDS", "0.1")
    application = create_app()

    with TestClient(application) as client:
        org = client.post("/api/orgs", json={"name": "Scheduled Runs"}).json()
        agent = client.post(
            f"/api/orgs/{org['id']}/agents",
            json={
                "name": "Timer Runner",
                "runtimeConfig": {"heartbeat": {"enabled": True, "intervalSec": 0.1}},
                "agentRuntimeConfig": {
                    "command": sys.executable,
                    "args": ["-c", "print('timer-ok')"],
                },
            },
        ).json()
        runs: list[dict[str, Any]] = []
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            runs = client.get(
                f"/api/orgs/{org['id']}/heartbeat-runs?agentId={agent['id']}"
            ).json()
            if any(
                run["invocationSource"] == "timer" and run["status"] == "succeeded"
                for run in runs
            ):
                break
            time.sleep(0.05)
        stop_event = getattr(application.state, "heartbeat_scheduler_stop_event", None)
        if stop_event is not None:
            stop_event.set()
        scheduler_task = getattr(application.state, "heartbeat_scheduler_task", None)
        if scheduler_task is not None:
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not scheduler_task.done():
                time.sleep(0.02)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            dispatch_tasks = list(
                getattr(application.state, "heartbeat_dispatch_tasks", set())
            )
            if not dispatch_tasks or all(task.done() for task in dispatch_tasks):
                break
            time.sleep(0.02)

    assert any(
        run["invocationSource"] == "timer" and run["status"] == "succeeded"
        for run in runs
    )
