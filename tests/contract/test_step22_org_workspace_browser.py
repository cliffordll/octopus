from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

from packages.database.schema import Base, Organization
from server.app import app as fastapi_app
from server.services.workspace_paths import organization_workspace_root


@fastapi_app.middleware("http")
async def _inject_workspace_browser_actor(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    actor_type = request.headers.get("x-test-actor-type")
    if actor_type:
        request.state.actor = {
            "type": actor_type,
            "id": request.headers.get("x-test-actor-id", "test-actor"),
            "orgId": request.headers.get("x-test-org-id"),
        }
    return await call_next(request)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def app(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> FastAPI:
    root = Path("pytest-tmp") / "org-workspace-browser"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("OCTOPUS_HOME", str(root / "octopus-home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "test")
    fastapi_app.state.session_factory = session_factory
    return fastapi_app


async def _seed_org(session_factory: async_sessionmaker[AsyncSession]) -> str:
    async with session_factory() as session:
        org = Organization(
            url_key="workspace-browser",
            name="Workspace Browser",
            issue_prefix="WB",
        )
        session.add(org)
        await session.commit()
        return org.id


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    org_id: str,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(
            method,
            path,
            json=json,
            headers={"x-test-actor-type": "board", "x-test-org-id": org_id},
        )
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.status_code, response.json()
    return response.status_code, response.content


@pytest.mark.anyio
async def test_org_workspace_browser_lists_and_reads_artifacts(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    org_id = await _seed_org(session_factory)
    artifact = (
        organization_workspace_root(org_id) / "artifacts" / "reports" / "summary.md"
    )
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"# Summary\n\nhello")

    list_code, listed = await _request(
        app, "GET", f"/api/orgs/{org_id}/workspace/files?path=artifacts", org_id=org_id
    )
    assert list_code == 200
    assert listed["directoryPath"] == "artifacts"
    assert listed["rootExists"] is True
    assert listed["entries"] == [
        {"name": "reports", "path": "artifacts/reports", "isDirectory": True}
    ]

    read_code, detail = await _request(
        app,
        "GET",
        f"/api/orgs/{org_id}/workspace/file?path=artifacts/reports/summary.md",
        org_id=org_id,
    )
    assert read_code == 200
    assert detail["filePath"] == "artifacts/reports/summary.md"
    assert detail["content"] == "# Summary\n\nhello"
    assert detail["contentType"] == "text/markdown"
    assert detail["previewKind"] == "text"


@pytest.mark.anyio
async def test_org_workspace_browser_supports_image_content(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    org_id = await _seed_org(session_factory)
    image = organization_workspace_root(org_id) / "artifacts" / "shot.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    read_code, detail = await _request(
        app,
        "GET",
        f"/api/orgs/{org_id}/workspace/file?path=artifacts/shot.png",
        org_id=org_id,
    )
    assert read_code == 200
    assert detail["previewKind"] == "image"
    assert detail["content"] is None
    assert detail["contentPath"].endswith("path=artifacts%2Fshot.png")

    content_code, content = await _request(
        app,
        "GET",
        f"/api/orgs/{org_id}/workspace/file/content?path=artifacts/shot.png",
        org_id=org_id,
    )
    assert content_code == 200
    assert content == b"\x89PNG\r\n\x1a\n"


@pytest.mark.anyio
async def test_org_workspace_browser_rejects_path_escape(
    app: FastAPI, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    org_id = await _seed_org(session_factory)

    code, body = await _request(
        app, "GET", f"/api/orgs/{org_id}/workspace/files?path=../outside", org_id=org_id
    )

    assert code == 422
    assert "inside the organization workspace root" in body["detail"]
