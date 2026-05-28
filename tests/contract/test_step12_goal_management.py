from __future__ import annotations

import importlib
import importlib.util
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.responses import Response

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.schema import Base, Organization
from server.app import create_app


def test_goal_contract_modules_define_step12_boundary() -> None:
    modules = (
        "packages.shared.api_paths.goals",
        "packages.shared.constants.goal",
        "packages.shared.types.goal",
        "packages.shared.validators.goal",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.goals")
    constants = importlib.import_module("packages.shared.constants.goal")
    validators = importlib.import_module("packages.shared.validators.goal")
    assert paths.ORG_GOAL_LIST_PATH == "/api/orgs/{orgId}/goals"
    assert paths.GOAL_DETAIL_PATH == "/api/goals/{id}"
    assert paths.GOAL_DEPENDENCIES_PATH == "/api/goals/{id}/dependencies"
    assert constants.GOAL_LEVELS == ("organization", "team", "agent", "task")
    assert constants.GOAL_STATUSES == ("planned", "active", "achieved", "cancelled")
    payload = validators.validate_create_goal({"title": "Ship Step 12"})
    assert payload["level"] == "task"
    assert payload["status"] == "planned"
    with pytest.raises(ValueError, match="level"):
        validators.validate_create_goal({"title": "Bad", "level": "invalid"})


def test_goal_tables_match_step12_boundary() -> None:
    schema = importlib.import_module("packages.database.schema")
    assert schema.Goal.__tablename__ == "goals"
    assert schema.ProjectGoal.__tablename__ == "project_goals"
    assert isinstance(schema.Goal.__table__, Table)
    assert {"goals", "project_goals"}.issubset(
        {table.name for table in Base.metadata.sorted_tables}
    )
    assert {index.name for index in schema.Goal.__table__.indexes} == {
        "goals_company_idx"
    }


async def test_upgrade_to_head_creates_goal_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "step12-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select name from sqlite_master "
                    "where type='table' and name in ('goals', 'project_goals')"
                )
            )
            names = {row[0] for row in rows}
    finally:
        await engine.dispose()
    assert names == {"goals", "project_goals"}


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
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker
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


async def _seed_org(session_factory: async_sessionmaker, key: str) -> str:
    async with session_factory() as session:
        org = Organization(url_key=key, name=key, issue_prefix=key[:6].upper())
        session.add(org)
        await session.commit()
        return org.id


async def test_goal_routes_crud_project_links_issue_fallback_and_dependencies(
    app: FastAPI, session_factory: async_sessionmaker
) -> None:
    org_id = await _seed_org(session_factory, "goals-contract")
    _, owner = await _request(
        app, "POST", f"/api/orgs/{org_id}/agents", json={"name": "Goal Owner"}
    )
    create_code, root = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/goals",
        json={
            "title": "Organization Objective",
            "level": "organization",
            "status": "active",
            "ownerAgentId": owner["id"],
        },
    )
    assert create_code == 201
    assert root["ownerAgentId"] == owner["id"]

    _, project = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/projects",
        json={"name": "Linked Project", "goalIds": [root["id"]]},
    )
    assert project["goalId"] == root["id"]
    assert project["goalIds"] == [root["id"]]
    assert project["goals"] == [{"id": root["id"], "title": root["title"]}]

    _, issue = await _request(
        app, "POST", f"/api/orgs/{org_id}/issues", json={"title": "Fallback Issue"}
    )
    assert issue["goalId"] == root["id"]

    dependencies_code, dependencies = await _request(
        app, "GET", f"/api/goals/{root['id']}/dependencies"
    )
    assert dependencies_code == 200
    assert dependencies["counts"]["linkedProjects"] == 1
    assert dependencies["counts"]["linkedIssues"] == 1
    assert set(dependencies["blockers"]) == {
        "last_root_organization_goal",
        "linked_projects",
        "linked_issues",
    }

    delete_code, blocked = await _request(app, "DELETE", f"/api/goals/{root['id']}")
    assert delete_code == 409
    assert blocked["detail"]["dependencies"]["canDelete"] is False


async def test_agent_cannot_list_goals_from_another_organization(
    app: FastAPI, session_factory: async_sessionmaker
) -> None:
    org_id = await _seed_org(session_factory, "goals-private")
    code, _ = await _request(
        app,
        "GET",
        f"/api/orgs/{org_id}/goals",
        headers={"x-test-agent-id": "agent-1", "x-test-org-id": "other-org"},
    )
    assert code == 403
