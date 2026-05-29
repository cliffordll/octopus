from __future__ import annotations

import importlib
import importlib.util
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import ActivityLog, Agent, Base, Organization
from server.app import create_app


def test_step17_org_skill_contract_exposes_paths_and_validators() -> None:
    modules = (
        "packages.shared.api_paths.organization_skills",
        "packages.shared.validators.organization_skills",
        "packages.shared.types.organization_skill",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.organization_skills")
    validators = importlib.import_module(
        "packages.shared.validators.organization_skills"
    )

    assert paths.ORG_SKILL_LIST_PATH == "/api/orgs/{orgId}/skills"
    assert paths.ORG_SKILL_DETAIL_PATH == "/api/orgs/{orgId}/skills/{skillId}"
    assert paths.ORG_SKILL_FILE_PATH == "/api/orgs/{orgId}/skills/{skillId}/files"
    assert validators.validate_create_organization_skill(
        {
            "name": "  Code Review  ",
            "slug": "  code-review  ",
            "description": "  Review code  ",
            "markdown": "Use this skill.",
        }
    ) == {
        "name": "Code Review",
        "slug": "code-review",
        "description": "Review code",
        "markdown": "Use this skill.",
    }
    assert validators.validate_update_organization_skill_file(
        {"path": " SKILL.md ", "content": "# Updated"}
    ) == {"path": "SKILL.md", "content": "# Updated"}


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    try:
        yield application, factory
    finally:
        await engine.dispose()


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body, params=params)
    if response.content:
        return response.status_code, response.json()
    return response.status_code, None


async def _seed_org(factory: async_sessionmaker, name: str) -> str:
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=name.lower().replace(" ", "-"),
                name=name,
                issue_prefix=org_id[:6].upper(),
            )
        )
        await session.commit()
    return org_id


async def _seed_agent(factory: async_sessionmaker, org_id: str) -> str:
    agent_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Skill Agent",
                workspace_key="skill-agent",
                role="individual_contributor",
                agent_runtime_type="codex_local",
                agent_runtime_config={},
            )
        )
        await session.commit()
    return agent_id


async def test_org_skill_crud_file_update_and_activity(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory, "Step 17 Skills")

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/skills",
        json_body={
            "name": "  Code Review  ",
            "slug": "  code-review  ",
            "description": "  Review code before merge  ",
            "markdown": "# Code Review\nCheck tests.",
        },
    )
    assert create_code == 201
    assert created["orgId"] == org_id
    assert created["slug"] == "code-review"
    assert created["key"] == "code-review"
    assert created["description"] == "Review code before merge"
    assert created["fileInventory"] == [{"path": "SKILL.md", "kind": "skill"}]

    list_code, listed = await _request(application, "GET", f"/api/orgs/{org_id}/skills")
    assert list_code == 200
    listed_by_id = {item["id"]: item for item in listed}
    assert created["id"] in listed_by_id
    assert listed_by_id[created["id"]]["sourceBadge"] == "local"
    assert listed_by_id[created["id"]]["editable"] is True

    detail_code, detail = await _request(
        application, "GET", f"/api/orgs/{org_id}/skills/{created['id']}"
    )
    assert detail_code == 200
    assert detail["markdown"] == "# Code Review\nCheck tests."

    file_code, file_detail = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/skills/{created['id']}/files",
        params={"path": "SKILL.md"},
    )
    assert file_code == 200
    assert file_detail["content"] == "# Code Review\nCheck tests."
    assert file_detail["markdown"] is True

    patch_code, patched_file = await _request(
        application,
        "PATCH",
        f"/api/orgs/{org_id}/skills/{created['id']}/files",
        json_body={"path": "SKILL.md", "content": "# Code Review\nUpdated."},
    )
    assert patch_code == 200
    assert patched_file["content"] == "# Code Review\nUpdated."

    delete_code, deleted = await _request(
        application, "DELETE", f"/api/orgs/{org_id}/skills/{created['id']}"
    )
    assert delete_code == 200
    assert deleted["id"] == created["id"]

    empty_code, empty = await _request(application, "GET", f"/api/orgs/{org_id}/skills")
    assert empty_code == 200
    assert created["id"] not in {item["id"] for item in empty}

    async with factory() as session:
        actions = [
            row.action
            for row in (
                await session.execute(
                    select(ActivityLog).where(ActivityLog.org_id == org_id)
                )
            )
            .scalars()
            .all()
        ]
    assert actions == [
        "organization.skill_created",
        "organization.skill_file_updated",
        "organization.skill_deleted",
    ]


async def test_org_skill_list_seeds_bundled_skills(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory, "Step 17 Bundled Skills")

    bundled_root = Path.cwd() / "server" / "skills" / "bundled"
    (bundled_root / "control-plane").mkdir(parents=True)
    (bundled_root / "control-plane" / "SKILL.md").write_text(
        "---\nname: control-plane\ndescription: Manage control plane tasks.\n---\n\nUse it.",
        encoding="utf-8",
    )
    (bundled_root / "skill-creator").mkdir(parents=True)
    (bundled_root / "skill-creator" / "SKILL.md").write_text(
        "---\nname: skill-creator\ndescription: Create durable skills.\n---\n\nUse it.",
        encoding="utf-8",
    )

    list_code, listed = await _request(application, "GET", f"/api/orgs/{org_id}/skills")

    assert list_code == 200
    keys = [skill["key"] for skill in listed]
    assert keys[:7] == [
        "skills/para-memory-files",
        "skills/control-plane",
        "skills/create-agent",
        "skills/create-plugin",
        "skills/skill-creator",
        "skills/skill-optimizer",
        "skills/conversation-to-skill",
    ]
    assert listed[0]["sourceBadge"] == "built-in"
    assert listed[0]["sourceLabel"] == "Built-in skill"
    assert listed[0]["editable"] is False
    assert listed[0]["description"]

    file_code, file_detail = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/skills/{listed[0]['id']}/files",
        params={"path": "SKILL.md"},
    )
    assert file_code == 200
    assert file_detail["content"].startswith("---\nname: para-memory-files")


async def test_org_skill_routes_accept_organization_url_key(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory, "Step 17 Url Key Skills")
    org_ref = "step-17-url-key-skills"

    list_code, listed = await _request(
        application, "GET", f"/api/orgs/{org_ref}/skills"
    )

    assert list_code == 200
    assert listed
    assert {skill["orgId"] for skill in listed} == {org_id}

    detail_code, detail = await _request(
        application,
        "GET",
        f"/api/orgs/{org_ref}/skills/{listed[0]['id']}",
    )
    assert detail_code == 200
    assert detail["orgId"] == org_id


async def test_org_skill_is_available_to_agent_skill_snapshot(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory, "Step 17 Skill Runtime")
    agent_id = await _seed_agent(factory, org_id)

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/skills",
        json_body={"name": "Review", "slug": "review", "markdown": "Review code."},
    )
    assert create_code == 201

    sync_code, snapshot = await _request(
        application,
        "POST",
        f"/api/agents/{agent_id}/skills/sync",
        json_body={"desiredSkills": [created["key"]]},
    )
    assert sync_code == 200
    entries = {entry["key"]: entry for entry in snapshot["entries"]}
    assert entries["review"]["desired"] is True
    assert entries["review"]["sourceClass"] == "organization"
    assert entries["review"]["description"] == "Review code."


async def test_org_skill_scope_and_path_guard(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory, "Skill Owner")
    other_org_id = await _seed_org(factory, "Skill Other")

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/skills",
        json_body={"name": "Owner Skill", "slug": "owner-skill"},
    )
    assert create_code == 201

    cross_code, cross = await _request(
        application, "GET", f"/api/orgs/{other_org_id}/skills/{created['id']}"
    )
    assert cross_code == 404
    assert cross["detail"] == "Skill not found"

    bad_path_code, bad_path = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/skills/{created['id']}/files",
        params={"path": "../secret.txt"},
    )
    assert bad_path_code == 422
    assert "path" in bad_path["detail"]
