from __future__ import annotations

import importlib
import importlib.util
from collections.abc import AsyncIterator
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import ActivityLog, Base, Organization
from server.app import create_app


def test_step17_org_resource_contract_exposes_paths_and_validators() -> None:
    modules = (
        "packages.shared.api_paths.organizations",
        "packages.shared.validators.resources",
        "packages.shared.types.resource",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.organizations")
    validators = importlib.import_module("packages.shared.validators.resources")

    assert paths.ORG_RESOURCE_LIST_PATH == "/api/orgs/{orgId}/resources"
    assert paths.ORG_RESOURCE_DETAIL_PATH == (
        "/api/orgs/{orgId}/resources/{resourceId}"
    )
    assert validators.validate_create_organization_resource(
        {
            "name": "  Repository  ",
            "kind": "url",
            "locator": "  https://example.test/repo  ",
            "description": "  docs  ",
            "metadata": {"branch": "main"},
        }
    ) == {
        "name": "Repository",
        "kind": "url",
        "locator": "https://example.test/repo",
        "description": "docs",
        "metadata": {"branch": "main"},
    }
    assert validators.validate_update_organization_resource({"description": "   "}) == {
        "description": None
    }


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
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
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body)
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


async def test_org_resource_crud_and_activity(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory, "Step 17 Resources")

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/resources",
        json_body={
            "name": "  Runbook  ",
            "kind": "url",
            "locator": "  https://example.test/runbook  ",
            "description": "  Primary runbook  ",
            "metadata": {"owner": "platform"},
        },
    )
    assert create_code == 201
    assert created["orgId"] == org_id
    assert created["name"] == "Runbook"
    assert created["locator"] == "https://example.test/runbook"
    assert created["description"] == "Primary runbook"
    assert created["metadata"] == {"owner": "platform"}

    list_code, listed = await _request(
        application, "GET", f"/api/orgs/{org_id}/resources"
    )
    assert list_code == 200
    assert [item["id"] for item in listed] == [created["id"]]

    patch_code, patched = await _request(
        application,
        "PATCH",
        f"/api/orgs/{org_id}/resources/{created['id']}",
        json_body={"description": "", "metadata": None},
    )
    assert patch_code == 200
    assert patched["description"] is None
    assert patched["metadata"] is None

    delete_code, deleted = await _request(
        application, "DELETE", f"/api/orgs/{org_id}/resources/{created['id']}"
    )
    assert delete_code == 200
    assert deleted["id"] == created["id"]

    empty_code, empty = await _request(
        application, "GET", f"/api/orgs/{org_id}/resources"
    )
    assert empty_code == 200
    assert empty == []

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
        "organization.resource.created",
        "organization.resource.updated",
        "organization.resource.deleted",
    ]


async def test_org_resource_scope_and_not_found(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory, "Resource Owner")
    other_org_id = await _seed_org(factory, "Resource Other")

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/resources",
        json_body={"name": "Repo", "kind": "url", "locator": "https://example.test"},
    )
    assert create_code == 201

    cross_patch_code, cross_patch = await _request(
        application,
        "PATCH",
        f"/api/orgs/{other_org_id}/resources/{created['id']}",
        json_body={"name": "Wrong org"},
    )
    assert cross_patch_code == 404
    assert cross_patch["detail"] == "Organization resource not found"

    cross_delete_code, cross_delete = await _request(
        application,
        "DELETE",
        f"/api/orgs/{other_org_id}/resources/{created['id']}",
    )
    assert cross_delete_code == 404
    assert cross_delete["detail"] == "Organization resource not found"
