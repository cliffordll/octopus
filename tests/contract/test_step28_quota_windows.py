from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Base, Organization
from server.app import create_app


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


async def _request(app: FastAPI, path: str) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(path)
    return response.status_code, response.json()


async def test_org_quota_windows_aggregates_success_and_failure(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, factory = app
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"quota-{uuid.uuid4().hex[:8]}",
                name="Quota Org",
                issue_prefix=f"QT{uuid.uuid4().hex[:4].upper()}",
            )
        )
        await session.commit()

    async def fake_get_runtime_quota_windows(runtime_type: str) -> dict[str, Any]:
        if runtime_type == "codex_local":
            return {
                "provider": "openai",
                "source": "codex_local",
                "ok": True,
                "windows": [{"kind": "requests", "resetsAt": "2026-06-08T12:00:00Z"}],
            }
        raise RuntimeError("provider offline")

    monkeypatch.setattr(
        "server.services.quota_windows.list_quota_runtime_types",
        lambda: ["codex_local", "claude_local"],
    )
    monkeypatch.setattr(
        "server.services.quota_windows.get_runtime_quota_windows",
        fake_get_runtime_quota_windows,
    )

    code, body = await _request(application, f"/api/orgs/{org_id}/costs/quota-windows")

    assert code == 200
    assert body["orgId"] == org_id
    assert body["relation"]["quota"] == "provider usage window evidence"
    assert len(body["providers"]) == 2
    assert body["providers"][0]["provider"] == "openai"
    assert body["providers"][0]["ok"] is True
    assert body["providers"][1]["provider"] == "anthropic"
    assert body["providers"][1]["ok"] is False
    assert "provider offline" in body["providers"][1]["error"]
