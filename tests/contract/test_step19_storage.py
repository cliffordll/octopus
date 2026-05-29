from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Asset, Base, Organization
from server.app import create_app


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker, Path]]:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_STORAGE_DIR", str(tmp_path / "storage"))
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    try:
        yield application, factory, tmp_path / "storage"
    finally:
        await engine.dispose()


async def _request(
    app: FastAPI,
    method: str,
    path: str,
) -> tuple[int, dict[str, str], bytes]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path)
    return response.status_code, dict(response.headers), response.content


async def _seed_org(factory: async_sessionmaker) -> str:
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"storage-{org_id[:8]}",
                name="Step 19 Storage",
                issue_prefix="S19",
            )
        )
        await session.commit()
    return org_id


async def test_local_storage_service_put_get_head_delete(tmp_path: Path) -> None:
    from server.storage import create_local_storage_service

    storage = create_local_storage_service(tmp_path / "objects")
    stored = await storage.put_file(
        org_id="org-1",
        namespace="chat/messages",
        original_filename="hello.txt",
        content_type="text/plain",
        body=b"hello storage",
    )

    assert stored["provider"] == "local_disk"
    assert stored["objectKey"].startswith("org-1/chat/messages/")
    assert stored["byteSize"] == len(b"hello storage")
    assert len(stored["sha256"]) == 64

    head = await storage.head_object("org-1", stored["objectKey"])
    assert head["exists"] is True
    assert head.get("contentLength") == len(b"hello storage")

    content = await storage.get_object_bytes("org-1", stored["objectKey"])
    assert content == b"hello storage"

    with pytest.raises(ValueError, match="organization"):
        await storage.get_object_bytes("other-org", stored["objectKey"])
    with pytest.raises(ValueError, match="Invalid object key"):
        await storage.get_object_bytes("org-1", "org-1/../secret.txt")

    await storage.delete_object("org-1", stored["objectKey"])
    missing = await storage.head_object("org-1", stored["objectKey"])
    assert missing["exists"] is False


async def test_asset_content_route_streams_stored_object(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    from server.storage import create_local_storage_service

    application, factory, storage_root = app
    org_id = await _seed_org(factory)
    storage = create_local_storage_service(storage_root)
    application.state.storage_service = storage
    stored = await storage.put_file(
        org_id=org_id,
        namespace="assets/tests",
        original_filename="report.txt",
        content_type="text/plain",
        body=b"asset body",
    )
    asset_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Asset(
                id=asset_id,
                org_id=org_id,
                provider=stored["provider"],
                object_key=stored["objectKey"],
                content_type=stored["contentType"],
                byte_size=stored["byteSize"],
                sha256=stored["sha256"],
                original_filename=stored["originalFilename"],
            )
        )
        await session.commit()

    code, headers, body = await _request(
        application, "GET", f"/api/assets/{asset_id}/content"
    )

    assert code == 200
    assert headers["content-type"].startswith("text/plain")
    assert headers["x-content-type-options"] == "nosniff"
    assert body == b"asset body"


async def test_asset_content_route_rejects_missing_asset(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, _, _ = app

    code, _, body = await _request(
        application, "GET", f"/api/assets/{uuid.uuid4()}/content"
    )

    assert code == 404
    assert b"Asset not found" in body
