from __future__ import annotations

import asyncio
import importlib
import importlib.util
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from alembic import command
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import BigInteger, Table, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.responses import Response

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.migrations.runner import _build_config, upgrade_to_head
from packages.database.schema import (
    ActivityLog,
    Agent,
    AgentWakeupRequest,
    Base,
    HeartbeatRun,
    Issue,
    IssueComment,
    Organization,
)
from server.app import create_app
from server.services.heartbeat import (
    _issue_passive_followup_delay,
    dispatch_all_queued_runs,
    dispatch_queued_agent,
)


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


def test_passive_followup_delay_uses_configured_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS", "90")

    assert _issue_passive_followup_delay() == timedelta(seconds=90)


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
    issue_paths = importlib.import_module("packages.shared.api_paths.issues")
    constants = importlib.import_module("packages.shared.constants.agent")
    validators = importlib.import_module("packages.shared.validators.agent")

    assert paths.ORG_AGENT_LIST_PATH == "/api/orgs/{orgId}/agents"
    assert paths.ORG_AGENT_HIRES_PATH == "/api/orgs/{orgId}/agent-hires"
    assert (
        paths.ORG_AGENT_NAME_SUGGESTION_PATH
        == "/api/orgs/{orgId}/agents/name-suggestion"
    )
    assert paths.AGENT_DETAIL_PATH == "/api/agents/{id}"
    assert paths.AGENT_INBOX_PATH == "/api/agents/{id}/inbox-lite"
    assert issue_paths.ISSUE_PASSIVE_FOLLOWUP_PATH == (
        "/api/issues/{id}/passive-followup"
    )
    assert paths.AGENT_ME_INBOX_PATH == "/api/agents/me/inbox-lite"
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
        "openclaw_local",
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


async def test_agent_inbox_lite_lists_assignee_and_reviewer_work(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="agent-inbox")
    agent_id = str(uuid.uuid4())
    other_agent_id = str(uuid.uuid4())
    build_issue_id = str(uuid.uuid4())
    comment_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="Inbox Owner",
                    role="engineer",
                    status="idle",
                ),
                Agent(
                    id=other_agent_id,
                    org_id=org_id,
                    name="Other",
                    role="engineer",
                    status="idle",
                ),
                Issue(
                    org_id=org_id,
                    identifier="INB-1",
                    title="Review me",
                    status="in_review",
                    priority="high",
                    reviewer_agent_id=agent_id,
                ),
                Issue(
                    id=build_issue_id,
                    org_id=org_id,
                    identifier="INB-2",
                    title="Build me",
                    status="in_progress",
                    priority="medium",
                    assignee_agent_id=agent_id,
                    checkout_run_id="run-checkout",
                    execution_run_id="run-exec",
                ),
                IssueComment(
                    id=comment_id,
                    org_id=org_id,
                    issue_id=build_issue_id,
                    body="Please update the implementation plan before continuing.",
                ),
                AgentWakeupRequest(
                    org_id=org_id,
                    agent_id=agent_id,
                    source="assignment",
                    trigger_detail="system",
                    reason="issue_comment_added",
                    payload={"issueId": build_issue_id, "commentId": comment_id},
                    status="queued",
                ),
                Issue(
                    org_id=org_id,
                    identifier="INB-3",
                    title="Ignore done",
                    status="done",
                    priority="medium",
                    assignee_agent_id=agent_id,
                ),
                Issue(
                    org_id=org_id,
                    identifier="INB-4",
                    title="Ignore other",
                    status="todo",
                    priority="medium",
                    assignee_agent_id=other_agent_id,
                ),
            ]
        )
        await session.commit()

    code, body = await _request(app, "GET", f"/api/agents/{agent_id}/inbox-lite")

    assert code == 200
    assert [(row["relationship"], row["identifier"]) for row in body] == [
        ("reviewer", "INB-1"),
        ("assignee", "INB-2"),
    ]
    assert body[1]["checkoutRunId"] == "run-checkout"
    assert body[1]["executionRunId"] == "run-exec"
    assert body[1]["wakeReason"] == "issue_comment_added"
    assert body[1]["wakeCommentId"] == comment_id
    assert body[1]["commentPreview"] == (
        "Please update the implementation plan before continuing."
    )

    code, own_body = await _request(
        app,
        "GET",
        "/api/agents/me/inbox-lite",
        headers={"x-test-agent-id": agent_id, "x-test-org-id": org_id},
    )
    assert code == 200
    assert own_body == body

    code, denied = await _request(
        app,
        "GET",
        f"/api/agents/{other_agent_id}/inbox-lite",
        headers={"x-test-agent-id": agent_id, "x-test-org-id": org_id},
    )
    assert code == 403
    assert denied["detail"] == "Agent cannot access another agent inbox"


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
    assert constants.HEARTBEAT_RUN_PURPOSES == (
        "task_execution",
        "closeout_followup",
        "review",
        "heartbeat",
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


def test_upgrade_to_head_backfills_all_bundled_skills(tmp_path: Path) -> None:
    db_path = tmp_path / "agent-skill-backfill.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"
    config = _build_config(database_url)
    command.upgrade(config, "20260603_000016")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            insert into organizations (
                id, url_key, name, status, issue_prefix, issue_counter,
                budget_monthly_cents, spent_monthly_cents,
                require_board_approval_for_new_agents,
                default_chat_issue_creation_mode
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "org-1",
                "skill-backfill",
                "Skill Backfill",
                "active",
                "SB",
                0,
                0,
                0,
                False,
                "manual_approval",
            ),
        )
        connection.executemany(
            """
            insert into agents (
                id, org_id, name, workspace_key, role, status,
                agent_runtime_type, agent_runtime_config, runtime_config,
                budget_monthly_cents, spent_monthly_cents, permissions
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "agent-1",
                    "org-1",
                    "Existing Agent",
                    "agent-existing",
                    "general",
                    "idle",
                    "process",
                    json.dumps({}),
                    json.dumps({}),
                    0,
                    0,
                    json.dumps({}),
                ),
                (
                    "agent-2",
                    "org-1",
                    "Terminated Agent",
                    "agent-terminated",
                    "general",
                    "terminated",
                    "process",
                    json.dumps({}),
                    json.dumps({}),
                    0,
                    0,
                    json.dumps({}),
                ),
            ],
        )
        connection.execute(
            """
            insert into agent_enabled_skills (id, org_id, agent_id, skill_key)
            values (?, ?, ?, ?)
            """,
            ("custom-skill-1", "org-1", "agent-1", "custom/existing-skill"),
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            select agent_id, skill_key
            from agent_enabled_skills
            order by agent_id, skill_key
            """
        ).fetchall()

    assert rows == [
        ("agent-1", "custom/existing-skill"),
        ("agent-1", "skills/control-plane"),
        ("agent-1", "skills/conversation-to-skill"),
        ("agent-1", "skills/create-agent"),
        ("agent-1", "skills/create-plugin"),
        ("agent-1", "skills/para-memory-files"),
        ("agent-1", "skills/skill-creator"),
        ("agent-1", "skills/skill-optimizer"),
    ]


def test_heartbeat_tables_match_step11c_boundary() -> None:
    schema = importlib.import_module("packages.database.schema")
    assert schema.HeartbeatRun.__tablename__ == "heartbeat_runs"
    assert "run_purpose" in schema.HeartbeatRun.__table__.c
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
            columns = {
                row[1]
                for row in (
                    await conn.execute(text("pragma table_info('heartbeat_runs')"))
                )
            }
    finally:
        await engine.dispose()
    assert names == {"heartbeat_runs", "heartbeat_run_events"}
    assert "run_purpose" in columns


def test_run_purpose_migration_backfills_existing_passive_followup(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "step11c-run-purpose.db"
    config = _build_config(f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(config, "20260612_000022")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            insert into organizations (
                id,
                url_key,
                name,
                status,
                issue_prefix,
                issue_counter,
                budget_monthly_cents,
                spent_monthly_cents,
                require_board_approval_for_new_agents,
                default_chat_issue_creation_mode
            )
            values (
                'org-1',
                'org-1',
                'Org 1',
                'active',
                'ORG',
                0,
                0,
                0,
                1,
                'manual_approval'
            )
            """
        )
        connection.execute(
            """
            insert into agents (
                id,
                org_id,
                name,
                role,
                status,
                agent_runtime_type,
                agent_runtime_config,
                runtime_config,
                budget_monthly_cents,
                spent_monthly_cents,
                permissions
            )
            values (
                'agent-1',
                'org-1',
                'Agent 1',
                'engineer',
                'idle',
                'process',
                '{}',
                '{}',
                0,
                0,
                '{}'
            )
            """
        )
        connection.execute(
            """
            insert into heartbeat_runs
                (
                    id,
                    org_id,
                    agent_id,
                    invocation_source,
                    status,
                    log_compressed,
                    process_loss_retry_count,
                    context_snapshot
                )
            values
                (
                    'run-1',
                    'org-1',
                    'agent-1',
                    'automation',
                    'succeeded',
                    0,
                    0,
                    '{"wakeReason":"issue_passive_followup"}'
                )
            """
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        purpose = connection.execute(
            "select run_purpose from heartbeat_runs where id = 'run-1'"
        ).fetchone()

    assert purpose == ("closeout_followup",)


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
                "runId": request.headers.get("x-test-run-id")
                or request.headers.get("x-octopus-run-id"),
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


async def test_issue_closeout_routes_accept_identifier_refs(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="identifier-closeout")
    agent_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Closer",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            Issue(
                id=str(uuid.uuid4()),
                org_id=org_id,
                identifier="IDC-17",
                title="Close by identifier",
                status="in_progress",
                priority="medium",
                assignee_agent_id=agent_id,
            )
        )
        await session.commit()

    code, body = await _request(
        app,
        "PATCH",
        "/api/issues/IDC-17",
        json={"status": "done", "comment": "Finished from CLI."},
        headers={
            "x-test-agent-id": agent_id,
            "x-test-org-id": org_id,
            "x-test-run-id": "run-identifier-closeout",
        },
    )

    assert code == 200
    assert body["status"] == "done"
    async with session_factory() as session:
        activities = (
            (
                await session.execute(
                    select(ActivityLog).where(ActivityLog.entity_id == body["id"])
                )
            )
            .scalars()
            .all()
        )
    assert activities[-1].action == "issue.updated"
    assert activities[-1].run_id == "run-identifier-closeout"


async def test_assignee_done_with_reviewer_requests_review_instead_of_closing(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="reviewer-done")
    assignee_id = str(uuid.uuid4())
    reviewer_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=assignee_id,
                    org_id=org_id,
                    name="Assignee",
                    role="engineer",
                    status="idle",
                ),
                Agent(
                    id=reviewer_id,
                    org_id=org_id,
                    name="Reviewer",
                    role="reviewer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    identifier="REV-17",
                    title="Needs review",
                    status="in_progress",
                    priority="medium",
                    assignee_agent_id=assignee_id,
                    reviewer_agent_id=reviewer_id,
                    checkout_run_id="run-assignee-done",
                    execution_run_id="run-assignee-done",
                ),
            ]
        )
        await session.commit()

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "done", "comment": "Ready for review."},
        headers={
            "x-test-agent-id": assignee_id,
            "x-test-org-id": org_id,
            "x-test-run-id": "run-assignee-done",
        },
    )

    assert code == 200
    assert body["status"] == "in_review"
    async with session_factory() as session:
        issue = await session.get_one(Issue, issue_id)
        wakeups = (
            (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == reviewer_id
                    )
                )
            )
            .scalars()
            .all()
        )
        activities = (
            (
                await session.execute(
                    select(ActivityLog).where(ActivityLog.entity_id == issue_id)
                )
            )
            .scalars()
            .all()
        )

    assert issue.status == "in_review"
    assert issue.completed_at is None
    assert len(wakeups) == 1
    assert wakeups[0].reason == "issue_review_requested"
    assert wakeups[0].source == "review"
    assert wakeups[0].payload["mutation"] == "assignee_done"
    assert activities[-1].action == "issue.updated"
    assert activities[-1].run_id == "run-assignee-done"
    assert activities[-1].details["status"] == "in_review"
    assert activities[-1].details["requestedStatus"] == "done"


async def test_repeated_assignee_done_requests_new_reviewer_wakeup(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="reviewer-done-repeat")
    assignee_id = str(uuid.uuid4())
    reviewer_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=assignee_id,
                    org_id=org_id,
                    name="Assignee",
                    role="engineer",
                    status="idle",
                ),
                Agent(
                    id=reviewer_id,
                    org_id=org_id,
                    name="Reviewer",
                    role="reviewer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    identifier="REV-18",
                    title="Repeated review",
                    status="in_progress",
                    priority="medium",
                    assignee_agent_id=assignee_id,
                    reviewer_agent_id=reviewer_id,
                ),
            ]
        )
        await session.commit()

    first_code, first_body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "done", "comment": "First pass ready."},
        headers={
            "x-test-agent-id": assignee_id,
            "x-test-org-id": org_id,
            "x-test-run-id": "run-assignee-done-1",
        },
    )

    assert first_code == 200
    assert first_body["status"] == "in_review"
    await _wait_for_dispatch(app)
    async with session_factory() as session:
        issue = await session.get_one(Issue, issue_id)
        issue.status = "in_progress"
        await session.commit()

    second_code, second_body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "done", "comment": "Second pass ready."},
        headers={
            "x-test-agent-id": assignee_id,
            "x-test-org-id": org_id,
            "x-test-run-id": "run-assignee-done-2",
        },
    )

    assert second_code == 200
    assert second_body["status"] == "in_review"
    await _wait_for_dispatch(app)
    async with session_factory() as session:
        wakeups = (
            (
                await session.execute(
                    select(AgentWakeupRequest)
                    .where(AgentWakeupRequest.agent_id == reviewer_id)
                    .order_by(AgentWakeupRequest.created_at)
                )
            )
            .scalars()
            .all()
        )

    assert len(wakeups) == 2
    assert [wakeup.payload["mutation"] for wakeup in wakeups] == [
        "assignee_done",
        "assignee_done",
    ]
    assert wakeups[0].idempotency_key != wakeups[1].idempotency_key


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


async def test_agent_create_materializes_upstream_heartbeat_policy_defaults(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="heartbeat-defaults")

    create_code, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={"name": "Defaults", "role": "engineer"},
    )
    assert create_code == 201
    assert created["runtimeConfig"]["heartbeat"] == {
        "enabled": True,
        "intervalSec": 300,
        "wakeOnDemand": True,
        "preflightEnabled": True,
        "maxConcurrentRuns": 3,
    }

    async with session_factory() as session:
        persisted = await session.get(Agent, created["id"])
    assert persisted is not None
    assert (
        persisted.runtime_config["heartbeat"] == created["runtimeConfig"]["heartbeat"]
    )

    detail_code, detail = await _request(app, "GET", f"/api/agents/{created['id']}")
    assert detail_code == 200
    assert detail["runtimeConfig"]["heartbeat"] == created["runtimeConfig"]["heartbeat"]

    config_code, config = await _request(
        app, "GET", f"/api/agents/{created['id']}/configuration"
    )
    assert config_code == 200
    assert config["runtimeConfig"]["heartbeat"] == created["runtimeConfig"]["heartbeat"]


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
    assert body["agent"]["name"] == "engineer-1"
    assert body["agent"]["reportsTo"] == ceo["id"]


async def test_agent_hired_by_agent_uses_role_sequence_and_reports_to_creator(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="agent-create-sequence")
    _, ceo = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={"name": "CEO", "role": "ceo"},
    )

    first_code, first = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agent-hires",
        json={"name": "System", "role": "engineer"},
        headers={"x-test-agent-id": ceo["id"], "x-test-org-id": org_id},
    )
    second_code, second = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agent-hires",
        json={"name": "Builder", "role": "engineer"},
        headers={"x-test-agent-id": ceo["id"], "x-test-org-id": org_id},
    )

    assert first_code == 201
    assert second_code == 201
    assert first["agent"]["name"] == "engineer-1"
    assert first["agent"]["reportsTo"] == ceo["id"]
    assert second["agent"]["name"] == "engineer-2"
    assert second["agent"]["reportsTo"] == ceo["id"]


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
    assert merged["agentRuntimeConfig"]["cwd"] == "workspace"
    assert merged["agentRuntimeConfig"]["model"] == "updated"
    assert merged["agentRuntimeConfig"]["instructionsBundleMode"] == "managed"
    assert merged["agentRuntimeConfig"]["instructionsEntryFile"] == "SOUL.md"
    assert merged["agentRuntimeConfig"]["instructionsRootPath"]
    assert merged["agentRuntimeConfig"]["instructionsFilePath"]

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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.delenv("OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS", raising=False)
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
            "source": "assignment",
            "triggerDetail": "system",
            "reason": "issue_execute",
            "payload": {
                "issueId": issue["id"],
                "wakeReason": "issue_execute",
            },
        },
    )
    assert wake_code == 202
    await _wait_for_dispatch(app)

    _, detail = await _request(app, "GET", f"/api/heartbeat-runs/{run['id']}")
    assert detail["status"] == "failed"
    assert detail["errorCode"] == "closeout_missing"
    issue_code, issue_after = await _request(app, "GET", f"/api/issues/{issue['id']}")
    assert issue_code == 200
    assert issue_after["status"] == "in_progress"

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
        "previousRunId": run["id"],
        "attempt": 1,
        "reason": "missing_closure",
    }
    assert rows[0].source == "automation"
    assert rows[0].status == "scheduled"
    assert rows[0].idempotency_key == f"issue_passive_followup:{run['id']}"
    requested_at = rows[0].requested_at
    if requested_at.tzinfo is None:
        requested_at = requested_at.replace(tzinfo=UTC)
    assert requested_at > datetime.now(UTC) + timedelta(minutes=29)

    async with session_factory() as session:
        followup_run = (
            await session.execute(
                select(HeartbeatRun).where(HeartbeatRun.wakeup_request_id == rows[0].id)
            )
        ).scalar_one_or_none()
        issue_row = await session.get(Issue, issue["id"])
        assert issue_row is not None
        assert issue_row.execution_run_id is None
        assert issue_row.checkout_run_id is None

    assert followup_run is None

    await dispatch_queued_agent(app.state.session_factory, agent["id"])

    async with session_factory() as session:
        followup_run = (
            await session.execute(
                select(HeartbeatRun).where(HeartbeatRun.wakeup_request_id == rows[0].id)
            )
        ).scalar_one_or_none()

    assert followup_run is None

    async with session_factory() as session:
        wakeup_row = await session.get(AgentWakeupRequest, rows[0].id)
        assert wakeup_row is not None
        wakeup_row.requested_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    await dispatch_all_queued_runs(app.state.session_factory)

    async with session_factory() as session:
        followup_run = (
            await session.execute(
                select(HeartbeatRun).where(HeartbeatRun.wakeup_request_id == rows[0].id)
            )
        ).scalar_one()
        issue_row = await session.get(Issue, issue["id"])
        assert issue_row is not None
        assert followup_run.invocation_source == "automation"
        assert followup_run.run_purpose == "closeout_followup"
        assert followup_run.status == "failed"
        assert followup_run.error_code == "closeout_missing"
        assert followup_run.context_snapshot is not None
        assert followup_run.context_snapshot["wakeReason"] == "issue_passive_followup"
        assert followup_run.context_snapshot["wakeSource"] == "passive_issue_followup"
        assert followup_run.context_snapshot["passiveFollowup"]["attempt"] == 1
        assert followup_run.context_snapshot["passiveFollowup"]["maxAttempts"] == 2
        assert (
            followup_run.context_snapshot["passiveFollowup"]["reason"]
            == "missing_closure"
        )
        assert issue_row.execution_run_id is None
        assert issue_row.checkout_run_id is None

    _, followup_detail = await _request(
        app, "GET", f"/api/heartbeat-runs/{followup_run.id}"
    )
    assert followup_detail["runPurpose"] == "closeout_followup"


async def test_issue_passive_followup_endpoint_promotes_scheduled_wakeup(
    app: FastAPI,
    session_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.delenv("OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS", raising=False)
    org_id = await _seed_org(session_factory, key="manual-passive-promote")
    _, agent = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Manual Followup Agent",
            "agentRuntimeConfig": {
                "command": sys.executable,
                "args": ["-c", "print('manual followup')"],
            },
        },
    )
    _, issue = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={"title": "Manual closeout needed", "status": "todo"},
    )
    async with session_factory() as session:
        await session.execute(
            text(
                "update issues set assignee_agent_id = :agent_id where id = :issue_id"
            ),
            {"agent_id": agent["id"], "issue_id": issue["id"]},
        )
        await session.commit()

    _, run = await _request(
        app,
        "POST",
        f"/api/agents/{agent['id']}/wakeup",
        json={
            "source": "assignment",
            "triggerDetail": "system",
            "reason": "issue_execute",
            "payload": {"issueId": issue["id"], "wakeReason": "issue_execute"},
        },
    )
    await _wait_for_dispatch(app)

    async with session_factory() as session:
        scheduled = (
            await session.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == agent["id"],
                    AgentWakeupRequest.reason == "issue_passive_followup",
                )
            )
        ).scalar_one()
        assert scheduled.status == "scheduled"
        assert scheduled.run_id is None

    followup_code, followup = await _request(
        app,
        "POST",
        f"/api/issues/{issue['id']}/passive-followup",
    )

    assert followup_code == 202
    assert followup["runPurpose"] == "closeout_followup"
    assert followup["triggerDetail"] == "manual"
    assert followup["contextSnapshot"]["passiveFollowup"]["previousRunId"] == run["id"]
    assert followup["status"] in {"queued", "running", "succeeded"}

    async with session_factory() as session:
        wakeups = (
            (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent["id"],
                        AgentWakeupRequest.reason == "issue_passive_followup",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(wakeups) == 1
    assert wakeups[0].id == scheduled.id
    assert wakeups[0].run_id == followup["id"]


async def test_heartbeat_run_list_normalizes_legacy_trigger_detail(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="legacy-trigger-detail")
    agent_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Legacy Trigger Agent",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="automation",
                trigger_detail="issue_passive_followup",
                status="succeeded",
                run_purpose="closeout_followup",
                context_snapshot={
                    "issueId": str(uuid.uuid4()),
                    "wakeReason": "issue_passive_followup",
                },
            )
        )
        await session.commit()

    code, runs = await _request(app, "GET", f"/api/orgs/{org_id}/heartbeat-runs")

    assert code == 200
    legacy_run = next(row for row in runs if row["id"] == run_id)
    assert legacy_run["triggerDetail"] is None


async def test_issue_passive_followup_endpoint_creates_immediate_followup_without_scheduled_wakeup(
    app: FastAPI,
    session_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    org_id = await _seed_org(session_factory, key="manual-passive-immediate")
    _, agent = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Immediate Followup Agent",
            "agentRuntimeConfig": {
                "command": sys.executable,
                "args": ["-c", "print('manual followup')"],
            },
        },
    )
    _, issue = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={"title": "Immediate closeout needed", "status": "todo"},
    )
    async with session_factory() as session:
        await session.execute(
            text(
                "update issues set assignee_agent_id = :agent_id where id = :issue_id"
            ),
            {"agent_id": agent["id"], "issue_id": issue["id"]},
        )
        await session.commit()

    monkeypatch.setenv("OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS", "9999")
    _, run = await _request(
        app,
        "POST",
        f"/api/agents/{agent['id']}/wakeup",
        json={
            "source": "assignment",
            "triggerDetail": "system",
            "reason": "issue_execute",
            "payload": {"issueId": issue["id"], "wakeReason": "issue_execute"},
        },
    )
    await _wait_for_dispatch(app)
    async with session_factory() as session:
        await session.execute(
            text("delete from agent_wakeup_requests where agent_id = :agent_id"),
            {"agent_id": agent["id"]},
        )
        await session.commit()

    followup_code, followup = await _request(
        app,
        "POST",
        f"/api/issues/{issue['id']}/passive-followup",
    )

    assert followup_code == 202
    assert followup["runPurpose"] == "closeout_followup"
    assert followup["contextSnapshot"]["passiveFollowup"]["previousRunId"] == run["id"]
    assert followup["status"] in {"queued", "running", "succeeded"}

    async with session_factory() as session:
        wakeup = (
            await session.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == agent["id"],
                    AgentWakeupRequest.reason == "issue_passive_followup",
                )
            )
        ).scalar_one()

    assert wakeup.status in {"queued", "claimed", "succeeded"}
    assert wakeup.run_id == followup["id"]


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


async def test_successful_issue_run_without_closeout_is_failed_and_records_event(
    session_factory: async_sessionmaker,
) -> None:
    from packages.database.schema import ActivityLog, Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="issue-run-closeout-required")
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="Missing Closeout Agent",
                    role="engineer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title="Missing closeout",
                    status="in_progress",
                    assignee_agent_id=agent_id,
                ),
                HeartbeatRun(
                    id=run_id,
                    org_id=org_id,
                    agent_id=agent_id,
                    invocation_source="assignment",
                    trigger_detail="system",
                    status="succeeded",
                    run_purpose="task_execution",
                    context_snapshot={
                        "issueId": issue_id,
                        "wakeReason": "issue_execute",
                    },
                    finished_at=datetime.now(UTC),
                ),
            ]
        )
        await session.flush()
        final = await HeartbeatService(session)._enforce_closeout_governance_success(
            await session.get_one(Agent, agent_id),
            await session.get_one(HeartbeatRun, run_id),
        )
        activity = (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == issue_id,
                    ActivityLog.action == "issue.closure_needs_operator_review",
                )
            )
        ).scalar_one()

    assert final.status == "failed"
    assert final.error_code == "closeout_missing"
    assert "control-plane issue done" in (final.error or "")
    assert activity.run_id == run_id
    assert activity.details["originRunId"] == run_id
    assert activity.details["attempts"] == 1


async def test_user_comment_after_successful_issue_run_skips_passive_followup(
    session_factory: async_sessionmaker,
) -> None:
    from datetime import UTC, datetime, timedelta

    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="user-comment-closeout")
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    finished_at = datetime(2026, 6, 12, 10, 0, tzinfo=UTC)
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="User Comment Agent",
                    role="engineer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title="User comment handled",
                    status="in_progress",
                    assignee_agent_id=agent_id,
                ),
                HeartbeatRun(
                    id=run_id,
                    org_id=org_id,
                    agent_id=agent_id,
                    invocation_source="assignment",
                    trigger_detail="system",
                    status="succeeded",
                    run_purpose="task_execution",
                    context_snapshot={"issueId": issue_id},
                    finished_at=finished_at,
                ),
                ActivityLog(
                    org_id=org_id,
                    actor_type="user",
                    actor_id="user-1",
                    action="issue.comment_added",
                    entity_type="issue",
                    entity_id=issue_id,
                    created_at=finished_at + timedelta(minutes=1),
                    details={"body": "I will handle the closeout manually."},
                ),
            ]
        )
        await session.flush()
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


async def test_scheduled_passive_followup_skips_after_user_comment(
    session_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime, timedelta

    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    monkeypatch.setenv("OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS", "0")
    org_id = await _seed_org(session_factory, key="scheduled-user-comment")
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    finished_at = datetime(2026, 6, 12, 10, 0, tzinfo=UTC)
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="Scheduled User Comment Agent",
                    role="engineer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title="Scheduled followup handled",
                    status="in_progress",
                    assignee_agent_id=agent_id,
                ),
                HeartbeatRun(
                    id=run_id,
                    org_id=org_id,
                    agent_id=agent_id,
                    invocation_source="assignment",
                    trigger_detail="system",
                    status="succeeded",
                    run_purpose="task_execution",
                    context_snapshot={"issueId": issue_id},
                    finished_at=finished_at,
                ),
            ]
        )
        await session.flush()
        service = HeartbeatService(session)
        await service._queue_issue_passive_followup_if_needed(
            await session.get_one(Agent, agent_id),
            await session.get_one(HeartbeatRun, run_id),
        )
        session.add(
            ActivityLog(
                org_id=org_id,
                actor_type="user",
                actor_id="user-1",
                action="issue.comment_added",
                entity_type="issue",
                entity_id=issue_id,
                created_at=finished_at + timedelta(minutes=1),
                details={"body": "Taking this over."},
            )
        )
        await session.flush()
        agent_ids = await service.materialize_due_scheduled_wakeups()
        wakeup = (
            await session.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == agent_id,
                    AgentWakeupRequest.reason == "issue_passive_followup",
                )
            )
        ).scalar_one()
        runs = (
            (
                await session.execute(
                    select(HeartbeatRun).where(
                        HeartbeatRun.agent_id == agent_id,
                        HeartbeatRun.run_purpose == "closeout_followup",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert agent_ids == set()
    assert wakeup.status == "skipped"
    assert runs == []


async def test_issue_comment_skips_scheduled_passive_followup_without_assignment_wakeup(
    app: FastAPI,
    session_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setenv("OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS", "9999")
    org_id = await _seed_org(session_factory, key="comment-skips-closeout")
    _, agent = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Comment Skips Closeout Agent",
            "agentRuntimeConfig": {
                "command": sys.executable,
                "args": ["-c", "print('comment skips closeout')"],
            },
        },
    )
    _, issue = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={"title": "Comment stops closeout", "status": "todo"},
    )
    async with session_factory() as session:
        await session.execute(
            text(
                "update issues set assignee_agent_id = :agent_id where id = :issue_id"
            ),
            {"agent_id": agent["id"], "issue_id": issue["id"]},
        )
        await session.commit()

    await _request(
        app,
        "POST",
        f"/api/agents/{agent['id']}/wakeup",
        json={
            "source": "assignment",
            "triggerDetail": "system",
            "reason": "issue_execute",
            "payload": {"issueId": issue["id"], "wakeReason": "issue_execute"},
        },
    )
    await _wait_for_dispatch(app)

    comment_code, _ = await _request(
        app,
        "POST",
        f"/api/issues/{issue['id']}/comments",
        json={"body": "任务结束，人工处理收尾。"},
    )

    assert comment_code == 200
    async with session_factory() as session:
        wakeups = (
            (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    closeout_wakeups = [
        wakeup for wakeup in wakeups if wakeup.reason == "issue_passive_followup"
    ]
    comment_wakeups = [
        wakeup for wakeup in wakeups if wakeup.reason == "issue_comment_added"
    ]

    assert len(closeout_wakeups) == 1
    assert closeout_wakeups[0].status == "skipped"
    assert closeout_wakeups[0].error == "Issue has user comment after missing closeout"
    assert comment_wakeups == []


async def test_issue_passive_followup_endpoint_rejects_after_user_comment(
    app: FastAPI,
    session_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    org_id = await _seed_org(session_factory, key="manual-user-comment")
    _, agent = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Manual User Comment Agent",
            "agentRuntimeConfig": {
                "command": sys.executable,
                "args": ["-c", "print('manual user comment')"],
            },
        },
    )
    _, issue = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={"title": "Manual user comment handled", "status": "todo"},
    )
    async with session_factory() as session:
        await session.execute(
            text(
                "update issues set assignee_agent_id = :agent_id where id = :issue_id"
            ),
            {"agent_id": agent["id"], "issue_id": issue["id"]},
        )
        await session.commit()

    monkeypatch.setenv("OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS", "9999")
    _, run = await _request(
        app,
        "POST",
        f"/api/agents/{agent['id']}/wakeup",
        json={
            "source": "assignment",
            "triggerDetail": "system",
            "reason": "issue_execute",
            "payload": {"issueId": issue["id"], "wakeReason": "issue_execute"},
        },
    )
    await _wait_for_dispatch(app)
    async with session_factory() as session:
        finished_run = await session.get_one(HeartbeatRun, run["id"])
        session.add(
            ActivityLog(
                org_id=org_id,
                actor_type="user",
                actor_id="user-1",
                action="issue.comment_added",
                entity_type="issue",
                entity_id=issue["id"],
                created_at=(finished_run.finished_at or finished_run.created_at)
                + timedelta(minutes=1),
                details={"body": "I will close this out manually."},
            )
        )
        await session.commit()

    followup_code, followup = await _request(
        app,
        "POST",
        f"/api/issues/{issue['id']}/passive-followup",
    )

    assert followup_code == 409
    assert "user intervention" in followup["detail"]


async def test_successful_issue_run_with_closeout_done_skips_passive_followup(
    session_factory: async_sessionmaker,
) -> None:
    from datetime import UTC, datetime

    from packages.database.queries.activity_log import insert_activity_log
    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="closeout-done")
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Closeout Done Agent",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Closeout done",
                status="in_progress",
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
            action="issue.updated",
            entity_type="issue",
            entity_id=issue_id,
            agent_id=agent_id,
            run_id=run_id,
            details={"status": "done"},
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


async def test_successful_issue_run_with_closeout_block_skips_passive_followup(
    session_factory: async_sessionmaker,
) -> None:
    from datetime import UTC, datetime

    from packages.database.queries.activity_log import insert_activity_log
    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="closeout-block")
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Closeout Block Agent",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Closeout block",
                status="in_progress",
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
            action="issue.updated",
            entity_type="issue",
            entity_id=issue_id,
            agent_id=agent_id,
            run_id=run_id,
            details={"status": "blocked"},
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


async def test_reviewed_issue_comment_without_review_routing_queues_passive_followup(
    session_factory: async_sessionmaker,
) -> None:
    from packages.database.queries.activity_log import insert_activity_log
    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="reviewed-comment")
    assignee_id = str(uuid.uuid4())
    reviewer_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=assignee_id,
                    org_id=org_id,
                    name="Reviewed Assignee",
                    role="engineer",
                    status="idle",
                ),
                Agent(
                    id=reviewer_id,
                    org_id=org_id,
                    name="Reviewed Reviewer",
                    role="engineer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title="Reviewed comment",
                    status="in_progress",
                    assignee_agent_id=assignee_id,
                    reviewer_agent_id=reviewer_id,
                ),
                HeartbeatRun(
                    id=run_id,
                    org_id=org_id,
                    agent_id=assignee_id,
                    invocation_source="assignment",
                    trigger_detail="system",
                    status="succeeded",
                    context_snapshot={"issueId": issue_id},
                    finished_at=datetime.now(UTC),
                ),
            ]
        )
        await session.flush()
        await insert_activity_log(
            session,
            org_id=org_id,
            actor_type="agent",
            actor_id=assignee_id,
            action="issue.comment_added",
            entity_type="issue",
            entity_id=issue_id,
            agent_id=assignee_id,
            run_id=run_id,
            details={"commentId": str(uuid.uuid4())},
        )
        await HeartbeatService(session)._queue_issue_passive_followup_if_needed(
            await session.get_one(Agent, assignee_id),
            await session.get_one(HeartbeatRun, run_id),
        )
        rows = (
            (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == assignee_id,
                        AgentWakeupRequest.reason == "issue_passive_followup",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].payload["originRunId"] == run_id
    assert rows[0].payload["attempt"] == 1


async def test_passive_followup_exhaustion_without_reviewer_requests_operator_review(
    session_factory: async_sessionmaker,
) -> None:
    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="passive-exhaust-operator")
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    origin_run_id = str(uuid.uuid4())
    previous_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="Exhausted Assignee",
                    role="engineer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title="Exhausted operator review",
                    status="in_progress",
                    assignee_agent_id=agent_id,
                ),
                HeartbeatRun(
                    id=run_id,
                    org_id=org_id,
                    agent_id=agent_id,
                    invocation_source="automation",
                    trigger_detail="system",
                    status="succeeded",
                    context_snapshot={
                        "issueId": issue_id,
                        "wakeReason": "issue_passive_followup",
                        "passiveFollowup": {
                            "originRunId": origin_run_id,
                            "previousRunId": previous_run_id,
                            "attempt": 2,
                            "maxAttempts": 2,
                            "reason": "missing_closure",
                        },
                    },
                    finished_at=datetime.now(UTC),
                ),
            ]
        )
        await session.flush()
        await HeartbeatService(session)._queue_issue_passive_followup_if_needed(
            await session.get_one(Agent, agent_id),
            await session.get_one(HeartbeatRun, run_id),
        )
        wakeups = (
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
        activity = (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == issue_id,
                    ActivityLog.action == "issue.closure_needs_operator_review",
                )
            )
        ).scalar_one()

    assert wakeups == []
    assert activity.details["originRunId"] == origin_run_id
    assert activity.details["previousRunId"] == run_id
    assert activity.details["attempts"] == 2
    assert activity.details["maxAttempts"] == 2


async def test_passive_followup_exhaustion_with_reviewer_queues_convergence_review(
    session_factory: async_sessionmaker,
) -> None:
    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="passive-exhaust-reviewer")
    assignee_id = str(uuid.uuid4())
    reviewer_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    origin_run_id = str(uuid.uuid4())
    previous_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=assignee_id,
                    org_id=org_id,
                    name="Exhausted Reviewed Assignee",
                    role="engineer",
                    status="idle",
                ),
                Agent(
                    id=reviewer_id,
                    org_id=org_id,
                    name="Convergence Reviewer",
                    role="engineer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title="Exhausted reviewer review",
                    status="in_progress",
                    assignee_agent_id=assignee_id,
                    reviewer_agent_id=reviewer_id,
                ),
                HeartbeatRun(
                    id=run_id,
                    org_id=org_id,
                    agent_id=assignee_id,
                    invocation_source="automation",
                    trigger_detail="system",
                    status="succeeded",
                    context_snapshot={
                        "issueId": issue_id,
                        "wakeReason": "issue_passive_followup",
                        "passiveFollowup": {
                            "originRunId": origin_run_id,
                            "previousRunId": previous_run_id,
                            "attempt": 2,
                            "maxAttempts": 2,
                            "reason": "missing_closure",
                        },
                    },
                    finished_at=datetime.now(UTC),
                ),
            ]
        )
        await session.flush()
        await HeartbeatService(session)._queue_issue_passive_followup_if_needed(
            await session.get_one(Agent, assignee_id),
            await session.get_one(HeartbeatRun, run_id),
        )
        wakeup = (
            await session.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == reviewer_id,
                    AgentWakeupRequest.reason == "issue_convergence_review_requested",
                )
            )
        ).scalar_one()
        convergence_run = (
            await session.execute(
                select(HeartbeatRun).where(HeartbeatRun.wakeup_request_id == wakeup.id)
            )
        ).scalar_one()
        activity = (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == issue_id,
                    ActivityLog.action == "issue.convergence_review_requested",
                )
            )
        ).scalar_one()

    assert wakeup.source == "review"
    assert wakeup.payload == {
        "issueId": issue_id,
        "mutation": "passive_followup_exhausted",
    }
    assert convergence_run.agent_id == reviewer_id
    assert convergence_run.invocation_source == "review"
    assert convergence_run.status == "queued"
    assert convergence_run.context_snapshot["wakeReason"] == (
        "issue_convergence_review_requested"
    )
    assert convergence_run.context_snapshot["convergenceReview"]["attempts"] == 2
    assert activity.details["originRunId"] == origin_run_id
    assert activity.details["previousRunId"] == run_id


async def test_successful_passive_followup_without_closeout_is_failed_and_escalated(
    session_factory: async_sessionmaker,
) -> None:
    from packages.database.schema import ActivityLog, Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="passive-closeout-false-success")
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    origin_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="False Success Closeout Agent",
                    role="engineer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title="False success closeout",
                    status="in_progress",
                    assignee_agent_id=agent_id,
                ),
                HeartbeatRun(
                    id=run_id,
                    org_id=org_id,
                    agent_id=agent_id,
                    invocation_source="automation",
                    trigger_detail="system",
                    status="succeeded",
                    run_purpose="closeout_followup",
                    context_snapshot={
                        "issueId": issue_id,
                        "wakeReason": "issue_passive_followup",
                        "passiveFollowup": {
                            "originRunId": origin_run_id,
                            "previousRunId": origin_run_id,
                            "attempt": 1,
                            "maxAttempts": 2,
                            "reason": "missing_closure",
                        },
                    },
                    finished_at=datetime.now(UTC),
                ),
            ]
        )
        await session.flush()
        final = await HeartbeatService(session)._enforce_closeout_governance_success(
            await session.get_one(Agent, agent_id),
            await session.get_one(HeartbeatRun, run_id),
        )
        issue = await session.get_one(Issue, issue_id)
        activity = (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == issue_id,
                    ActivityLog.action == "issue.closure_needs_operator_review",
                )
            )
        ).scalar_one()

    assert final.status == "failed"
    assert final.error_code == "closeout_missing"
    assert "control-plane issue done" in (final.error or "")
    assert issue.status == "in_progress"
    assert activity.run_id == run_id
    assert activity.details["originRunId"] == origin_run_id
    assert activity.details["attempts"] == 1


async def test_successful_reviewer_run_without_decision_queues_review_closeout(
    session_factory: async_sessionmaker,
) -> None:
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


async def test_review_closeout_missing_run_without_decision_records_activity(
    session_factory: async_sessionmaker,
) -> None:
    from packages.database.schema import (
        ActivityLog,
        Agent,
        AgentWakeupRequest,
        HeartbeatRun,
        Issue,
    )
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="review-closeout-still-missing")
    reviewer_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    origin_run_id = str(uuid.uuid4())
    closeout_run_id = str(uuid.uuid4())
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
                title="Still needs review decision",
                status="in_review",
                reviewer_agent_id=reviewer_id,
            )
        )
        session.add(
            HeartbeatRun(
                id=closeout_run_id,
                org_id=org_id,
                agent_id=reviewer_id,
                invocation_source="review",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={
                    "issueId": issue_id,
                    "role": "reviewer",
                    "wakeSource": "review",
                    "wakeReason": "issue_review_closeout_missing",
                    "reviewCloseout": {
                        "originRunId": origin_run_id,
                        "previousRunId": origin_run_id,
                        "attempt": 1,
                        "maxAttempts": 1,
                    },
                },
                finished_at=datetime.now(UTC),
            )
        )
        await session.flush()
        await HeartbeatService(session)._queue_issue_passive_followup_if_needed(
            await session.get_one(Agent, reviewer_id),
            await session.get_one(HeartbeatRun, closeout_run_id),
        )
        activities = (
            (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.org_id == org_id,
                        ActivityLog.entity_type == "issue",
                        ActivityLog.entity_id == issue_id,
                        ActivityLog.action == "issue.review_closeout_missing",
                    )
                )
            )
            .scalars()
            .all()
        )
        wakeups = (
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

    assert len(activities) == 1
    assert activities[0].run_id == closeout_run_id
    assert activities[0].details["originRunId"] == origin_run_id
    assert activities[0].details["attempts"] == 1
    assert activities[0].details["maxAttempts"] == 1
    assert wakeups == []


async def test_review_closeout_missing_success_without_decision_is_failed(
    session_factory: async_sessionmaker,
) -> None:
    from packages.database.schema import ActivityLog, Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org_id = await _seed_org(session_factory, key="review-closeout-false-success")
    reviewer_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    origin_run_id = str(uuid.uuid4())
    closeout_run_id = str(uuid.uuid4())
    async with session_factory() as session:
        session.add_all(
            [
                Agent(
                    id=reviewer_id,
                    org_id=org_id,
                    name="Review False Success Agent",
                    role="engineer",
                    status="idle",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title="Review false success",
                    status="in_review",
                    reviewer_agent_id=reviewer_id,
                ),
                HeartbeatRun(
                    id=closeout_run_id,
                    org_id=org_id,
                    agent_id=reviewer_id,
                    invocation_source="review",
                    trigger_detail="system",
                    status="succeeded",
                    run_purpose="review",
                    context_snapshot={
                        "issueId": issue_id,
                        "role": "reviewer",
                        "wakeSource": "review",
                        "wakeReason": "issue_review_closeout_missing",
                        "reviewCloseout": {
                            "originRunId": origin_run_id,
                            "previousRunId": origin_run_id,
                            "attempt": 1,
                            "maxAttempts": 1,
                        },
                    },
                    finished_at=datetime.now(UTC),
                ),
            ]
        )
        await session.flush()
        final = await HeartbeatService(session)._enforce_closeout_governance_success(
            await session.get_one(Agent, reviewer_id),
            await session.get_one(HeartbeatRun, closeout_run_id),
        )
        activity = (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == issue_id,
                    ActivityLog.action == "issue.review_closeout_missing",
                )
            )
        ).scalar_one()

    assert final.status == "failed"
    assert final.error_code == "closeout_missing"
    assert "control-plane issue review" in (final.error or "")
    assert activity.run_id == closeout_run_id
    assert activity.details["originRunId"] == origin_run_id


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
                status="running",
                context_snapshot={"issueId": issue_id},
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

        active_run = await session.get_one(HeartbeatRun, active_run_id)
        active_run.status = "succeeded"
        active_run.finished_at = datetime.now(UTC)
        await service._release_issue_execution(active_run)
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
        "--skip-git-repo-check",
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
