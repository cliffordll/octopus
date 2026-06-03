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
    assert paths.ORG_SKILL_IMPORT_PATH == "/api/orgs/{orgId}/skills/import"
    assert paths.ORG_SKILL_SCAN_LOCAL_PATH == "/api/orgs/{orgId}/skills/scan-local"
    assert paths.ORG_SKILL_INSTALL_UPDATE_PATH == (
        "/api/orgs/{orgId}/skills/{skillId}/install-update"
    )
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
    assert validators.validate_import_organization_skill(
        {
            "sourcePath": " ./skills/review ",
            "slug": "review",
            "name": " Review ",
            "description": None,
            "overwrite": True,
        }
    ) == {
        "sourcePath": "./skills/review",
        "slug": "review",
        "name": "Review",
        "description": None,
        "overwrite": True,
    }
    assert validators.validate_scan_local_organization_skills(
        {"rootPath": " ./skills ", "importDiscovered": True}
    ) == {"rootPath": "./skills", "importDiscovered": True}


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
    (bundled_root / "para-memory-files" / "reference").mkdir(parents=True)
    (bundled_root / "para-memory-files" / "scripts").mkdir(parents=True)
    (bundled_root / "para-memory-files" / "templates").mkdir(parents=True)
    (bundled_root / "para-memory-files" / "SKILL.md").write_text(
        "---\nname: para-memory-files\ndescription: Memory files.\n---\n\nUse it.",
        encoding="utf-8",
    )
    (bundled_root / "para-memory-files" / "README.md").write_text(
        "# PARA Memory Files\n",
        encoding="utf-8",
    )
    (bundled_root / "para-memory-files" / "reference" / "methodology.md").write_text(
        "# Methodology\n",
        encoding="utf-8",
    )
    (bundled_root / "para-memory-files" / "scripts" / "sync.py").write_text(
        "print('sync')\n",
        encoding="utf-8",
    )
    (bundled_root / "para-memory-files" / "templates" / "note.md").write_text(
        "# Note\n",
        encoding="utf-8",
    )
    (bundled_root / "control-plane").mkdir(parents=True)
    (bundled_root / "control-plane" / "SKILL.md").write_text(
        "\ufeff---\nname: control-plane\ndescription: Manage control plane tasks.\n---\n\nUse it.",
        encoding="utf-8",
    )
    (bundled_root / "skill-creator").mkdir(parents=True)
    (bundled_root / "skill-creator" / "SKILL.md").write_text(
        "---\nname: skill-creator\ndescription: Create durable skills.\n---\n\nUse it.",
        encoding="utf-8",
    )
    community_root = Path.cwd() / "server" / "skills" / "community"
    (community_root / "deep-research" / "reference").mkdir(parents=True)
    (community_root / "deep-research" / "SKILL.md").write_text(
        "---\nname: deep-research\ndescription: Research deeply.\n---\n\nUse it.",
        encoding="utf-8",
    )
    (community_root / "deep-research" / "reference" / "methodology.md").write_text(
        "# Research Methodology\n",
        encoding="utf-8",
    )
    (community_root / "software-product-advisor").mkdir(parents=True)
    (community_root / "software-product-advisor" / "SKILL.md").write_text(
        "---\nname: software-product-advisor\ndescription: >\n  Advise product work.\n  Turn fuzzy concerns into clear next steps.\n---\n\nUse it.",
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
    assert {
        f"organization/{org_id}/deep-research",
        f"organization/{org_id}/software-product-advisor",
    } == {skill["key"] for skill in listed if skill["sourceBadge"] == "community"}
    assert listed[0]["sourceBadge"] == "built-in"
    assert listed[0]["sourceLabel"] == "Built-in skill"
    assert listed[0]["editable"] is False
    assert listed[0]["description"]
    assert listed[1]["description"] == "Manage control plane tasks."
    assert listed[0]["fileInventory"] == [
        {"path": "SKILL.md", "kind": "skill"},
        {"path": "README.md", "kind": "readme"},
        {"path": "reference/methodology.md", "kind": "reference"},
        {"path": "scripts/sync.py", "kind": "script"},
        {"path": "templates/note.md", "kind": "template"},
    ]

    file_code, file_detail = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/skills/{listed[0]['id']}/files",
        params={"path": "SKILL.md"},
    )
    assert file_code == 200
    assert file_detail["content"].startswith("---\nname: para-memory-files")

    reference_code, reference_detail = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/skills/{listed[0]['id']}/files",
        params={"path": "reference/methodology.md"},
    )
    assert reference_code == 200
    assert reference_detail["kind"] == "reference"
    assert reference_detail["content"] == "# Methodology\n"

    community = next(skill for skill in listed if skill["slug"] == "deep-research")
    advisor = next(
        skill for skill in listed if skill["slug"] == "software-product-advisor"
    )
    assert community["key"] == f"organization/{org_id}/deep-research"
    assert community["sourceBadge"] == "community"
    assert community["sourceLabel"] == "Community preset"
    assert community["editable"] is False
    assert community["editableReason"] == "Community preset skill"
    assert (
        advisor["description"]
        == "Advise product work. Turn fuzzy concerns into clear next steps."
    )
    assert community["fileInventory"] == [
        {"path": "SKILL.md", "kind": "skill"},
        {"path": "reference/methodology.md", "kind": "reference"},
    ]

    community_file_code, community_file = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/skills/{community['id']}/files",
        params={"path": "reference/methodology.md"},
    )
    assert community_file_code == 200
    assert community_file["content"] == "# Research Methodology\n"


async def test_org_skill_import_scan_and_install_update_local_source(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    application, factory = app
    org_id = await _seed_org(factory, "Step 17 External Skills")
    source_root = tmp_path / "external-skills"
    review_source = source_root / "review-skill"
    review_source.mkdir(parents=True)
    review_source.joinpath("SKILL.md").write_text(
        "---\nname: review-skill\ndescription: Review code carefully.\n---\n\nUse v1.",
        encoding="utf-8",
    )
    review_source.joinpath("references").mkdir()
    review_source.joinpath("references", "guide.md").write_text(
        "# Guide\n",
        encoding="utf-8",
    )

    scan_code, scan = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/skills/scan-local",
        json_body={"rootPath": str(source_root)},
    )
    assert scan_code == 200
    assert scan["imported"] == []
    assert scan["candidates"] == [
        {
            "sourcePath": str(review_source.resolve()),
            "slug": "review-skill",
            "name": "review-skill",
            "description": "Review code carefully.",
            "sourceRef": scan["candidates"][0]["sourceRef"],
            "alreadyImported": False,
            "skillId": None,
        }
    ]

    import_code, imported = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/skills/import",
        json_body={"sourcePath": str(review_source)},
    )
    assert import_code == 201
    assert imported["slug"] == "review-skill"
    assert imported["sourceType"] == "local_path"
    assert imported["sourceLocator"] == str(review_source.resolve())
    assert imported["sourceRef"] == scan["candidates"][0]["sourceRef"]
    assert imported["fileInventory"] == [
        {"path": "SKILL.md", "kind": "skill"},
        {"path": "references/guide.md", "kind": "reference"},
    ]

    installed_code, installed_file = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/skills/{imported['id']}/files",
        params={"path": "SKILL.md"},
    )
    assert installed_code == 200
    assert "Use v1." in installed_file["content"]

    duplicate_code, duplicate = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/skills/import",
        json_body={"sourcePath": str(review_source)},
    )
    assert duplicate_code == 409
    assert "already exists" in duplicate["detail"]

    review_source.joinpath("SKILL.md").write_text(
        "---\nname: review-skill\ndescription: Review code carefully.\n---\n\nUse v2.",
        encoding="utf-8",
    )
    status_code, update_status = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/skills/{imported['id']}/update-status",
    )
    assert status_code == 200
    assert update_status["supported"] is True
    assert update_status["hasUpdate"] is True
    assert update_status["latestRef"] != update_status["trackingRef"]

    install_code, updated = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/skills/{imported['id']}/install-update",
    )
    assert install_code == 200
    assert updated["sourceRef"] == update_status["latestRef"]

    updated_file_code, updated_file = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/skills/{imported['id']}/files",
        params={"path": "SKILL.md"},
    )
    assert updated_file_code == 200
    assert "Use v2." in updated_file["content"]

    scan_import_code, scan_import = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/skills/scan-local",
        json_body={"rootPath": str(source_root), "importDiscovered": True},
    )
    assert scan_import_code == 200
    assert scan_import["imported"] == []
    assert scan_import["candidates"][0]["alreadyImported"] is True
    assert scan_import["candidates"][0]["skillId"] == imported["id"]

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
        "organization.skill_imported",
        "organization.skill_update_installed",
    ]


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
    community_root = Path.cwd() / "server" / "skills" / "community"
    (community_root / "deep-research").mkdir(parents=True)
    (community_root / "deep-research" / "SKILL.md").write_text(
        "---\nname: deep-research\ndescription: Research deeply.\n---\n\nUse it.",
        encoding="utf-8",
    )

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
    community = entries[f"organization/{org_id}/deep-research"]
    assert community["selectionKey"] == f"org:organization/{org_id}/deep-research"
    assert community["runtimeName"] == "deep-research"
    assert community["sourceClass"] == "organization"
    assert community["origin"] == "community_preset"
    assert community["originLabel"] == "Community preset"
    assert community["description"] == "Research deeply."


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
