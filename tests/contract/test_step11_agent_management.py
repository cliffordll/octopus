from __future__ import annotations

import asyncio
import importlib
import importlib.util
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
import uuid

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger, Table, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.responses import Response

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.schema import AgentWakeupRequest, Base, Organization
from server.app import create_app


def test_agent_dependencies_preserve_existing_exports_with_heartbeat_service() -> None:
    dependencies = importlib.import_module("server.dependencies")
    assert {
        "get_session",
        "get_org_service",
        "get_issue_service",
        "get_approval_service",
        "get_project_service",
        "get_agent_service",
        "get_heartbeat_service",
    }.issubset(set(dependencies.__all__))


def test_agent_contract_modules_define_management_boundary() -> None:
    modules = (
        "packages.shared.api_paths.agents",
        "packages.shared.constants.agent",
        "packages.shared.types.agent",
        "packages.shared.validators.agent",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.agents")
    constants = importlib.import_module("packages.shared.constants.agent")
    validators = importlib.import_module("packages.shared.validators.agent")

    assert paths.ORG_AGENT_LIST_PATH == "/api/orgs/{orgId}/agents"
    assert paths.ORG_AGENT_HIRES_PATH == "/api/orgs/{orgId}/agent-hires"
    assert (
        paths.ORG_AGENT_NAME_SUGGESTION_PATH
        == "/api/orgs/{orgId}/agents/name-suggestion"
    )
    assert paths.AGENT_DETAIL_PATH == "/api/agents/{id}"
    assert paths.AGENT_ARCHIVE_PATH == "/api/agents/{id}/archive"
    assert paths.AGENT_PAUSE_PATH == "/api/agents/{id}/pause"
    assert paths.AGENT_CONFIGURATION_PATH == "/api/agents/{id}/configuration"
    assert (
        paths.ORG_AGENT_CONFIGURATIONS_PATH == "/api/orgs/{orgId}/agent-configurations"
    )
    assert paths.AGENT_CONFIG_REVISIONS_PATH == "/api/agents/{id}/config-revisions"
    assert paths.AGENT_RUNTIME_STATE_PATH == "/api/agents/{id}/runtime-state"
    assert paths.AGENT_TASK_SESSIONS_PATH == "/api/agents/{id}/task-sessions"
    assert constants.AGENT_STATUSES == (
        "active",
        "paused",
        "idle",
        "running",
        "error",
        "pending_approval",
        "terminated",
    )
    assert constants.AGENT_RUNTIME_TYPES == (
        "process",
        "http",
        "claude_local",
        "codex_local",
        "gemini_local",
        "opencode_local",
        "pi_local",
        "cursor",
        "openclaw_gateway",
        "hermes_local",
    )
    payload = validators.validate_create_agent({"name": "Operator"})
    assert payload["role"] == "general"
    assert payload["agentRuntimeType"] == "process"
    assert payload["agentRuntimeConfig"] == {}
    with pytest.raises(ValueError, match="role"):
        validators.validate_create_agent({"role": "invalid"})
    hire_payload = validators.validate_hire_agent(
        {"name": "Reviewer", "sourceIssueId": "issue-1"}
    )
    assert hire_payload["name"] == "Reviewer"
    assert hire_payload["sourceIssueId"] == "issue-1"
    assert validators.validate_reset_agent_session({"taskKey": "issue-1"}) == {
        "taskKey": "issue-1"
    }


def test_heartbeat_contract_modules_define_execution_boundary() -> None:
    paths = importlib.import_module("packages.shared.api_paths.heartbeat")
    constants = importlib.import_module("packages.shared.constants.heartbeat")
    validators = importlib.import_module("packages.shared.validators.heartbeat")

    assert paths.AGENT_WAKEUP_PATH == "/api/agents/{id}/wakeup"
    assert paths.AGENT_HEARTBEAT_INVOKE_PATH == "/api/agents/{id}/heartbeat/invoke"
    assert paths.ORG_HEARTBEAT_RUNS_PATH == "/api/orgs/{orgId}/heartbeat-runs"
    assert paths.HEARTBEAT_RUN_PATH == "/api/heartbeat-runs/{runId}"
    assert paths.HEARTBEAT_RUN_EVENTS_PATH == "/api/heartbeat-runs/{runId}/events"
    assert constants.HEARTBEAT_INVOCATION_SOURCES == (
        "timer",
        "assignment",
        "review",
        "on_demand",
        "automation",
    )
    assert constants.HEARTBEAT_RUN_STATUSES == (
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
    )
    assert validators.validate_wake_agent({"reason": "run now"}) == {
        "source": "on_demand",
        "reason": "run now",
        "forceFreshSession": False,
    }


def test_agent_schema_matches_step11a_boundary() -> None:
    schema = importlib.import_module("packages.database.schema")
    agent = schema.Agent
    assert agent.__tablename__ == "agents"
    assert isinstance(agent.__table__, Table)
    assert {index.name for index in agent.__table__.indexes} == {
        "agents_company_status_idx",
        "agents_company_reports_to_idx",
        "agents_org_workspace_key_idx",
    }
    assert "agents" in {table.name for table in Base.metadata.sorted_tables}


async def test_upgrade_to_head_creates_agents_table(tmp_path: Path) -> None:
    db_path = tmp_path / "step11a-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")

    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master "
                    "where type='table' and name = 'agents'"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()

    assert names == {"agents"}


def test_agent_state_tables_match_step11b_boundary() -> None:
    schema = importlib.import_module("packages.database.schema")
    expected = {
        "agent_config_revisions",
        "agent_runtime_state",
        "agent_task_sessions",
        "agent_wakeup_requests",
    }
    assert expected.issubset({table.name for table in Base.metadata.sorted_tables})
    assert schema.AgentConfigRevision.__tablename__ == "agent_config_revisions"
    assert schema.AgentRuntimeState.__tablename__ == "agent_runtime_state"
    assert schema.AgentTaskSession.__tablename__ == "agent_task_sessions"
    assert schema.AgentWakeupRequest.__tablename__ == "agent_wakeup_requests"


async def test_upgrade_to_head_creates_agent_state_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "step11b-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master where type='table' and name in "
                    "('agent_config_revisions', 'agent_runtime_state', "
                    "'agent_task_sessions', 'agent_wakeup_requests')"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()
    assert names == {
        "agent_config_revisions",
        "agent_runtime_state",
        "agent_task_sessions",
        "agent_wakeup_requests",
    }


def test_heartbeat_tables_match_step11c_boundary() -> None:
    schema = importlib.import_module("packages.database.schema")
    assert schema.HeartbeatRun.__tablename__ == "heartbeat_runs"
    assert schema.HeartbeatRunEvent.__tablename__ == "heartbeat_run_events"
    assert isinstance(schema.HeartbeatRunEvent.__table__.c.id.type, BigInteger)
    assert {"heartbeat_runs", "heartbeat_run_events"}.issubset(
        {table.name for table in Base.metadata.sorted_tables}
    )


async def test_upgrade_to_head_creates_heartbeat_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "step11c-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master where type='table' and name in "
                    "('heartbeat_runs', 'heartbeat_run_events')"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()
    assert names == {"heartbeat_runs", "heartbeat_run_events"}


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return create_session_factory(engine)


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker,
) -> FastAPI:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    application = create_app()
    application.state.session_factory = session_factory

    @application.middleware("http")
    async def inject_agent_actor(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        actor_id = request.headers.get("x-test-agent-id")
        if actor_id:
            request.state.actor = {
                "type": "agent",
                "id": actor_id,
                "agentId": actor_id,
                "orgId": request.headers["x-test-org-id"],
            }
        return await call_next(request)

    return application


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, json=json, headers=headers)
    return response.status_code, response.json()


async def _wait_for_dispatch(app: FastAPI) -> None:
    tasks = list(getattr(app.state, "heartbeat_dispatch_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


async def _seed_org(
    session_factory: async_sessionmaker,
    *,
    key: str,
    require_agent_approval: bool = True,
) -> str:
    async with session_factory() as session:
        org = Organization(
            id=str(uuid.uuid4()),
            url_key=key,
            name=key,
            issue_prefix=key[:3].upper(),
            require_board_approval_for_new_agents=require_agent_approval,
        )
        session.add(org)
        await session.commit()
        return org.id


async def test_agent_routes_manage_lifecycle_and_hide_terminated_agents(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="agents")

    create_code, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={"name": "Runner", "role": "engineer"},
    )
    assert create_code == 201
    assert created["orgId"] == org_id
    assert created["urlKey"] == "runner"
    assert created["status"] == "idle"
    assert created["agentRuntimeType"] == "process"

    detail_code, detail = await _request(app, "GET", f"/api/agents/{created['id']}")
    assert detail_code == 200
    assert detail["chainOfCommand"] == []
    assert detail["access"]["taskAssignSource"] == "none"

    patch_code, updated = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={"title": "Execution owner"},
    )
    assert patch_code == 200
    assert updated["title"] == "Execution owner"

    pause_code, paused = await _request(
        app, "POST", f"/api/agents/{created['id']}/pause"
    )
    assert pause_code == 200
    assert paused["status"] == "paused"
    assert paused["pauseReason"] == "manual"

    resume_code, resumed = await _request(
        app, "POST", f"/api/agents/{created['id']}/resume"
    )
    assert resume_code == 200
    assert resumed["status"] == "idle"
    assert resumed["pauseReason"] is None

    terminate_code, terminated = await _request(
        app, "POST", f"/api/agents/{created['id']}/terminate"
    )
    assert terminate_code == 200
    assert terminated["status"] == "terminated"

    list_code, listed = await _request(app, "GET", f"/api/orgs/{org_id}/agents")
    assert list_code == 200
    assert listed == []


async def test_agent_archive_route_terminates_and_hides_agent(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="agent-archive")
    create_code, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={"name": "Archive Me", "role": "engineer"},
    )
    assert create_code == 201

    archive_code, archived = await _request(
        app, "POST", f"/api/agents/{created['id']}/archive"
    )

    assert archive_code == 200
    assert archived["status"] == "terminated"
    list_code, listed = await _request(app, "GET", f"/api/orgs/{org_id}/agents")
    assert list_code == 200
    assert listed == []


async def test_agent_hire_directly_creates_agent_when_org_does_not_require_approval(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(
        session_factory, key="direct-hire", require_agent_approval=False
    )

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agent-hires",
        json={"name": "Reviewer", "role": "engineer", "budgetMonthlyCents": 1200},
    )

    assert code == 201
    assert body["approval"] is None
    assert body["agent"]["name"] == "Reviewer"
    assert body["agent"]["status"] == "idle"
    assert body["agent"]["budgetMonthlyCents"] == 1200


async def test_agent_hire_creates_pending_agent_and_approval_when_required(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(
        session_factory, key="approval-hire", require_agent_approval=True
    )

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agent-hires",
        json={"name": "Analyst", "role": "researcher"},
    )

    assert code == 201
    assert body["agent"]["status"] == "pending_approval"
    approval = body["approval"]
    assert approval["type"] == "hire_agent"
    assert approval["status"] == "pending"
    assert approval["payload"]["agentId"] == body["agent"]["id"]
    assert approval["payload"]["hire"]["name"] == "Analyst"

    wake_code, wake_body = await _request(
        app,
        "POST",
        f"/api/agents/{body['agent']['id']}/wakeup",
        json={"reason": "not yet"},
    )
    assert wake_code == 409
    assert "not invokable" in wake_body["detail"].lower()


async def test_ceo_agent_can_request_hire_with_board_approval(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(
        session_factory, key="ceo-hire", require_agent_approval=True
    )
    _, ceo = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={"name": "CEO", "role": "ceo"},
    )

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agent-hires",
        json={"name": "Builder", "role": "engineer"},
        headers={"x-test-agent-id": ceo["id"], "x-test-org-id": org_id},
    )

    assert code == 201
    assert body["agent"]["status"] == "pending_approval"
    assert body["approval"]["type"] == "hire_agent"
    assert body["approval"]["requestedByAgentId"] == ceo["id"]
    assert body["approval"]["requestedByUserId"] is None


async def test_non_ceo_agent_cannot_request_hire_without_create_permission(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(
        session_factory, key="worker-hire", require_agent_approval=True
    )
    _, worker = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={"name": "Worker", "role": "engineer"},
    )

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agent-hires",
        json={"name": "Another", "role": "engineer"},
        headers={"x-test-agent-id": worker["id"], "x-test-org-id": org_id},
    )

    assert code == 403
    assert "permission" in body["detail"].lower()


async def test_approving_hire_agent_approval_activates_pending_agent(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(
        session_factory, key="approve-hire", require_agent_approval=True
    )
    _, hire = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agent-hires",
        json={"name": "Operator", "role": "engineer"},
    )
    agent_id = hire["agent"]["id"]
    approval_id = hire["approval"]["id"]

    approve_code, approved = await _request(
        app,
        "POST",
        f"/api/approvals/{approval_id}/approve",
        json={"decisionNote": "approved"},
    )
    assert approve_code == 200
    assert approved["status"] == "approved"

    detail_code, detail = await _request(app, "GET", f"/api/agents/{agent_id}")
    assert detail_code == 200
    assert detail["status"] == "idle"


async def test_rejecting_hire_agent_approval_terminates_pending_agent(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(
        session_factory, key="reject-hire", require_agent_approval=True
    )
    _, hire = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agent-hires",
        json={"name": "Temporary", "role": "engineer"},
    )
    agent_id = hire["agent"]["id"]
    approval_id = hire["approval"]["id"]

    reject_code, rejected = await _request(
        app,
        "POST",
        f"/api/approvals/{approval_id}/reject",
        json={"decisionNote": "not needed"},
    )
    assert reject_code == 200
    assert rejected["status"] == "rejected"

    detail_code, detail = await _request(app, "GET", f"/api/agents/{agent_id}")
    assert detail_code == 200
    assert detail["status"] == "terminated"


async def test_agent_creation_without_name_uses_personal_name_suggestion(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="agent-names")

    suggestion_code, suggestion = await _request(
        app, "GET", f"/api/orgs/{org_id}/agents/name-suggestion"
    )
    assert suggestion_code == 200
    assert suggestion["name"] not in {"Agent", "Agent 2"}

    first_code, first = await _request(
        app, "POST", f"/api/orgs/{org_id}/agents", json={"role": "ceo"}
    )
    second_code, second = await _request(
        app, "POST", f"/api/orgs/{org_id}/agents", json={"role": "engineer"}
    )
    assert first_code == 201
    assert second_code == 201
    assert first["name"] not in {"Agent", "Agent 2"}
    assert second["name"] not in {"Agent", "Agent 2"}
    assert first["name"] != second["name"]


async def test_agent_manager_must_belong_to_same_organization(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    home_id = await _seed_org(session_factory, key="home")
    foreign_id = await _seed_org(session_factory, key="foreign")
    _, manager = await _request(
        app,
        "POST",
        f"/api/orgs/{foreign_id}/agents",
        json={"name": "Foreign Manager"},
    )

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{home_id}/agents",
        json={"name": "Worker", "reportsTo": manager["id"]},
    )
    assert code == 422
    assert "same organization" in body["detail"]


async def test_agent_update_merges_runtime_configuration_unless_replace_requested(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="adapter-config")
    _, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Configured",
            "agentRuntimeConfig": {"cwd": "workspace", "model": "initial"},
        },
    )

    code, merged = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={"agentRuntimeConfig": {"model": "updated"}},
    )
    assert code == 200
    assert merged["agentRuntimeConfig"] == {"cwd": "workspace", "model": "updated"}

    code, replaced = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={
            "agentRuntimeConfig": {"model": "only"},
            "replaceAgentRuntimeConfig": True,
        },
    )
    assert code == 200
    assert replaced["agentRuntimeConfig"] == {"model": "only"}


async def test_agent_configuration_revision_redacts_and_rolls_back(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="revision")
    _, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={"name": "Configured", "agentRuntimeConfig": {"model": "initial"}},
    )
    patch_code, _ = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={"agentRuntimeConfig": {"model": "next", "apiKey": "secret-value"}},
    )
    assert patch_code == 200

    config_code, config = await _request(
        app, "GET", f"/api/agents/{created['id']}/configuration"
    )
    assert config_code == 200
    assert config["agentRuntimeConfig"]["apiKey"] == "***REDACTED***"
    org_config_code, org_configs = await _request(
        app, "GET", f"/api/orgs/{org_id}/agent-configurations"
    )
    assert org_config_code == 200
    assert org_configs[0]["agentRuntimeConfig"]["apiKey"] == "***REDACTED***"

    revisions_code, revisions = await _request(
        app, "GET", f"/api/agents/{created['id']}/config-revisions"
    )
    assert revisions_code == 200
    assert revisions[0]["changedKeys"] == ["agentRuntimeConfig"]
    assert (
        revisions[0]["afterConfig"]["agentRuntimeConfig"]["apiKey"] == "***REDACTED***"
    )
    revision_code, revision = await _request(
        app,
        "GET",
        f"/api/agents/{created['id']}/config-revisions/{revisions[0]['id']}",
    )
    assert revision_code == 200
    assert revision["id"] == revisions[0]["id"]

    _, _ = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={
            "agentRuntimeConfig": {"model": "latest"},
            "replaceAgentRuntimeConfig": True,
        },
    )
    rollback_code, rolled_back = await _request(
        app,
        "POST",
        f"/api/agents/{created['id']}/config-revisions/{revisions[0]['id']}/rollback",
    )
    assert rollback_code == 422
    assert "redacted" in rolled_back["detail"].lower()

    _, first_safe = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={"runtimeConfig": {"heartbeat": "enabled"}},
    )
    assert first_safe["runtimeConfig"] == {"heartbeat": "enabled"}
    _, safe_revisions = await _request(
        app, "GET", f"/api/agents/{created['id']}/config-revisions"
    )
    safe_revision = next(
        revision
        for revision in safe_revisions
        if revision["changedKeys"] == ["runtimeConfig"]
    )
    _, _ = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={"runtimeConfig": {"heartbeat": "off"}},
    )
    rollback_code, rolled_back = await _request(
        app,
        "POST",
        f"/api/agents/{created['id']}/config-revisions/{safe_revision['id']}/rollback",
    )
    assert rollback_code == 200
    assert rolled_back["runtimeConfig"] == {"heartbeat": "enabled"}


async def test_agent_runtime_state_sessions_and_reset_routes(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    from packages.database.schema import AgentRuntimeState, AgentTaskSession

    org_id = await _seed_org(session_factory, key="sessions")
    _, created = await _request(
        app, "POST", f"/api/orgs/{org_id}/agents", json={"name": "Runtime"}
    )
    async with session_factory() as session:
        session.add(
            AgentRuntimeState(
                agent_id=created["id"],
                org_id=org_id,
                agent_runtime_type="process",
                session_id="legacy-session",
                state_json={"resume": True},
            )
        )
        session.add(
            AgentTaskSession(
                org_id=org_id,
                agent_id=created["id"],
                agent_runtime_type="process",
                task_key="issue-1",
                session_params_json={"password": "secret", "safe": "visible"},
                session_display_id="session-display",
            )
        )
        await session.commit()

    state_code, state = await _request(
        app, "GET", f"/api/agents/{created['id']}/runtime-state"
    )
    assert state_code == 200
    assert state["sessionDisplayId"] == "session-display"

    sessions_code, sessions = await _request(
        app, "GET", f"/api/agents/{created['id']}/task-sessions"
    )
    assert sessions_code == 200
    assert sessions[0]["sessionParamsJson"] == {
        "password": "***REDACTED***",
        "safe": "visible",
    }

    reset_code, reset = await _request(
        app,
        "POST",
        f"/api/agents/{created['id']}/runtime-state/reset-session",
        json={"taskKey": "issue-1"},
    )
    assert reset_code == 200
    assert reset["clearedTaskSessions"] == 1
    assert reset["sessionId"] is None
    assert reset["stateJson"] == {"resume": True}


async def test_agent_wakeup_executes_process_adapter_and_exposes_run(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    import sys

    org_id = await _seed_org(session_factory, key="heartbeat")
    _, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Executor",
            "agentRuntimeConfig": {
                "command": sys.executable,
                "args": ["-c", "print('adapter-ok')"],
            },
        },
    )

    wake_code, run = await _request(
        app,
        "POST",
        f"/api/agents/{created['id']}/wakeup",
        json={"reason": "contract-run"},
    )
    assert wake_code == 202
    assert run["status"] == "queued"
    assert run["invocationSource"] == "on_demand"
    await _wait_for_dispatch(app)

    list_code, runs = await _request(app, "GET", f"/api/orgs/{org_id}/heartbeat-runs")
    assert list_code == 200
    assert runs[0]["id"] == run["id"]

    detail_code, detail = await _request(app, "GET", f"/api/heartbeat-runs/{run['id']}")
    assert detail_code == 200
    assert detail["status"] == "succeeded"
    assert detail["resultJson"]["stdout"].strip() == "adapter-ok"

    events_code, events = await _request(
        app, "GET", f"/api/heartbeat-runs/{run['id']}/events"
    )
    assert events_code == 200
    assert [event["eventType"] for event in events] == [
        "lifecycle",
        "lifecycle",
        "adapter.invoke",
        "lifecycle",
        "log",
        "lifecycle",
    ]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert [event["message"].strip() for event in events] == [
        "run queued",
        "run started",
        "adapter invocation",
        events[3]["message"].strip(),
        "adapter-ok",
        "run succeeded",
    ]

    state_code, state = await _request(
        app, "GET", f"/api/agents/{created['id']}/runtime-state"
    )
    assert state_code == 200
    assert state["lastRunId"] == run["id"]
    assert state["lastRunStatus"] == "succeeded"


async def test_successful_issue_run_without_closeout_queues_passive_followup(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    import sys

    org_id = await _seed_org(session_factory, key="passive-followup")
    _, agent = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Closeout Agent",
            "agentRuntimeConfig": {
                "command": sys.executable,
                "args": ["-c", "print('worked')"],
            },
        },
    )
    _, issue = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={
            "title": "Needs closeout",
            "status": "todo",
        },
    )
    async with session_factory() as session:
        await session.execute(
            text(
                "update issues set assignee_agent_id = :agent_id where id = :issue_id"
            ),
            {"agent_id": agent["id"], "issue_id": issue["id"]},
        )
        await session.commit()

    wake_code, run = await _request(
        app,
        "POST",
        f"/api/agents/{agent['id']}/wakeup",
        json={
            "reason": "contract-issue-run",
            "payload": {
                "issueId": issue["id"],
                "wakeReason": "contract-issue-run",
            },
        },
    )
    assert wake_code == 202
    await _wait_for_dispatch(app)

    _, detail = await _request(app, "GET", f"/api/heartbeat-runs/{run['id']}")
    assert detail["status"] == "succeeded"
    issue_code, issue_after = await _request(app, "GET", f"/api/issues/{issue['id']}")
    assert issue_code == 200
    assert issue_after["status"] == "todo"

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(AgentWakeupRequest)
                    .where(
                        AgentWakeupRequest.agent_id == agent["id"],
                        AgentWakeupRequest.reason == "issue_passive_followup",
                    )
                    .order_by(AgentWakeupRequest.requested_at)
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].payload == {
        "issueId": issue["id"],
        "originRunId": run["id"],
        "mutation": "passive_followup",
    }
    assert rows[0].status == "queued"


async def test_successful_issue_run_with_closeout_comment_skips_passive_followup(
    session_factory: async_sessionmaker,
) -> None:
    from datetime import UTC, datetime

    from packages.database.queries.activity_log import insert_activity_log
    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="closeout-comment")
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Closeout Comment Agent",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Closeout comment",
                status="todo",
                assignee_agent_id=agent_id,
            )
        )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": issue_id},
                finished_at=datetime.now(UTC),
            )
        )
        await session.flush()
        await insert_activity_log(
            session,
            org_id=org_id,
            actor_type="agent",
            actor_id=agent_id,
            action="issue.comment_added",
            entity_type="issue",
            entity_id=issue_id,
            agent_id=agent_id,
            run_id=run_id,
            details={"commentId": str(uuid.uuid4())},
        )
        await HeartbeatService(session)._queue_issue_passive_followup_if_needed(
            await session.get_one(Agent, agent_id),
            await session.get_one(HeartbeatRun, run_id),
        )
        rows = (
            (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id,
                        AgentWakeupRequest.reason == "issue_passive_followup",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert rows == []


async def test_successful_reviewer_run_without_decision_queues_review_closeout(
    session_factory: async_sessionmaker,
) -> None:
    from datetime import UTC, datetime

    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="review-closeout")
    reviewer_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(
            Agent(
                id=reviewer_id,
                org_id=org_id,
                name="Review Closeout Agent",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Needs review decision",
                status="in_review",
                reviewer_agent_id=reviewer_id,
            )
        )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=reviewer_id,
                invocation_source="review",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={
                    "issueId": issue_id,
                    "role": "reviewer",
                    "wakeSource": "review",
                },
                finished_at=datetime.now(UTC),
            )
        )
        await session.flush()
        await HeartbeatService(session)._queue_issue_passive_followup_if_needed(
            await session.get_one(Agent, reviewer_id),
            await session.get_one(HeartbeatRun, run_id),
        )
        rows = (
            (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == reviewer_id,
                        AgentWakeupRequest.reason == "issue_review_closeout_missing",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].source == "review"
    assert rows[0].payload == {
        "issueId": issue_id,
        "originRunId": run_id,
        "previousRunId": run_id,
        "attempt": 1,
        "reason": "review_outcome_missing",
    }


async def test_issue_wakeup_defers_while_execution_locked_and_promotes_on_release(
    session_factory: async_sessionmaker,
) -> None:
    from datetime import UTC, datetime

    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="deferred-issue")
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    active_run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Deferred Agent",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            HeartbeatRun(
                id=active_run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": issue_id},
                finished_at=datetime.now(UTC),
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Locked issue",
                status="in_progress",
                assignee_agent_id=agent_id,
                checkout_run_id=active_run_id,
                execution_run_id=active_run_id,
            )
        )
        await session.flush()

        service = HeartbeatService(session)
        deferred = await service.wakeup(
            agent_id,
            {
                "source": "assignment",
                "triggerDetail": "system",
                "reason": "issue_execute_again",
                "payload": {"issueId": issue_id, "mutation": "execute"},
                "contextSnapshot": {
                    "issueId": issue_id,
                    "source": "test.defer",
                    "wakeReason": "issue_execute_again",
                },
            },
            actor_type="system",
            actor_id="test",
            execute_immediately=False,
        )
        assert deferred is None
        wakeup = (
            (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id,
                        AgentWakeupRequest.status == "deferred_issue_execution",
                    )
                )
            )
            .scalars()
            .one()
        )

        await service._release_issue_execution(
            await session.get_one(HeartbeatRun, active_run_id)
        )
        await session.refresh(wakeup)
        issue = await session.get_one(Issue, issue_id)
        promoted = (
            await session.execute(
                select(HeartbeatRun).where(HeartbeatRun.wakeup_request_id == wakeup.id)
            )
        ).scalar_one()

    assert wakeup.status == "queued"
    assert wakeup.run_id == promoted.id
    assert promoted.status == "queued"
    assert promoted.context_snapshot["issueId"] == issue_id
    assert promoted.context_snapshot["source"] == "test.defer"
    assert issue.execution_run_id == promoted.id
    assert issue.checkout_run_id == promoted.id


async def test_agent_wakeup_executes_codex_local_adapter_and_persists_session_usage(
    app: FastAPI,
    session_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            captured["stdin"] = payload
            return (
                (
                    '{"type":"thread.started","thread_id":"thread-11e"}\n'
                    '{"type":"item.completed","item":{"type":"agent_message",'
                    '"text":"codex completed"}}\n'
                    '{"type":"turn.completed","usage":{"input_tokens":12,'
                    '"cached_input_tokens":3,"output_tokens":5}}\n'
                ).encode(),
                b"",
            )

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured["args"] = args
        captured["cwd"] = kwargs.get("cwd")
        return FakeCodexProcess()

    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    org_id = await _seed_org(session_factory, key="codex-runtime")
    _, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Codex Executor",
            "agentRuntimeType": "codex_local",
            "agentRuntimeConfig": {
                "command": "codex-test",
                "cwd": "workspace",
                "model": "gpt-5",
                "search": True,
                "dangerouslyBypassApprovalsAndSandbox": True,
                "promptTemplate": "Complete the assigned task.",
            },
        },
    )

    wake_code, run = await _request(
        app, "POST", f"/api/agents/{created['id']}/heartbeat/invoke"
    )
    assert wake_code == 202
    assert run["status"] == "queued"
    await _wait_for_dispatch(app)
    _, run = await _request(app, "GET", f"/api/heartbeat-runs/{run['id']}")
    assert run["status"] == "succeeded"
    assert captured["args"] == (
        "codex-test",
        "--search",
        "exec",
        "--json",
        "--disable",
        "plugins",
        "--dangerously-bypass-approvals-and-sandbox",
        "--model",
        "gpt-5",
        "-c",
        "skills.bundled.enabled=false",
        "-",
    )
    prompt = captured["stdin"].decode("utf-8")
    assert prompt.startswith("Complete the assigned task.")
    assert "## Runtime Tool Capability" in prompt
    assert "Do not guess tool input schemas" in prompt
    assert run["sessionIdAfter"] == "thread-11e"
    assert run["usageJson"] == {
        "inputTokens": 12,
        "cachedInputTokens": 3,
        "outputTokens": 5,
        "billingType": "subscription",
        "biller": "chatgpt",
    }
    assert run["resultJson"]["summary"] == "codex completed"

    _, state = await _request(app, "GET", f"/api/agents/{created['id']}/runtime-state")
    assert state["sessionId"] == "thread-11e"
    assert state["agentRuntimeType"] == "codex_local"


async def test_agent_execution_acceptance_flow_starts_with_org_creation(
    app: FastAPI,
) -> None:
    import sys

    org_code, org = await _request(app, "POST", "/api/orgs", json={"name": "Run Demo"})
    assert org_code == 200
    create_code, agent = await _request(
        app,
        "POST",
        f"/api/orgs/{org['id']}/agents",
        json={
            "name": "Acceptance Runner",
            "agentRuntimeConfig": {
                "command": sys.executable,
                "args": ["-c", "print('step-11-ok')"],
            },
        },
    )
    assert create_code == 201

    invoke_code, run = await _request(
        app, "POST", f"/api/agents/{agent['id']}/heartbeat/invoke"
    )
    assert invoke_code == 202
    assert run["status"] == "queued"
    await _wait_for_dispatch(app)

    detail_code, detail = await _request(app, "GET", f"/api/heartbeat-runs/{run['id']}")
    assert detail_code == 200
    assert detail["resultJson"]["stdout"].strip() == "step-11-ok"

    state_code, runtime_state = await _request(
        app, "GET", f"/api/agents/{agent['id']}/runtime-state"
    )
    assert state_code == 200
    assert runtime_state["lastRunId"] == run["id"]


async def test_agent_actor_cannot_invoke_another_agent(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="agent-invoke-scope")
    _, caller = await _request(
        app, "POST", f"/api/orgs/{org_id}/agents", json={"name": "Caller"}
    )
    _, target = await _request(
        app, "POST", f"/api/orgs/{org_id}/agents", json={"name": "Target"}
    )
    code, body = await _request(
        app,
        "POST",
        f"/api/agents/{target['id']}/wakeup",
        json={},
        headers={"x-test-agent-id": caller["id"], "x-test-org-id": org_id},
    )
    assert code == 403
    assert body["detail"] == "Agent can only invoke itself"


async def test_agent_cannot_list_other_organization(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="private")
    code, _ = await _request(
        app,
        "GET",
        f"/api/orgs/{org_id}/agents",
        headers={
            "x-test-agent-id": "agent-1",
            "x-test-org-id": "another-org",
        },
    )
    assert code == 403
