from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import (
    Asset,
    Base,
    ChatConversation,
    ChatMessage,
    Issue,
    Organization,
)
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


async def _seed_chat(factory: async_sessionmaker) -> tuple[str, str, str]:
    org_id = await _seed_org(factory)
    conversation_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            ChatConversation(
                id=conversation_id,
                org_id=org_id,
                title="Storage chat",
            )
        )
        session.add(
            ChatMessage(
                id=message_id,
                org_id=org_id,
                conversation_id=conversation_id,
                role="user",
                kind="message",
                status="completed",
                body="attach this",
            )
        )
        await session.commit()
    return org_id, conversation_id, message_id


async def _seed_issue(factory: async_sessionmaker) -> tuple[str, str]:
    org_id = await _seed_org(factory)
    issue_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Storage issue",
                status="todo",
                priority="medium",
            )
        )
        await session.commit()
    return org_id, issue_id


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


class _FakeObjectStorageClient:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
        ContentLength: int,
    ) -> None:
        assert ContentLength == len(Body)
        self.objects[(Bucket, Key)] = (Body, ContentType)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        body, _ = self.objects[(Bucket, Key)]
        return {
            "Body": BytesIO(body),
            "ContentLength": len(body),
            "LastModified": datetime(2026, 6, 3, tzinfo=UTC),
        }

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        body, _ = self.objects[(Bucket, Key)]
        return {"ContentLength": len(body)}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop((Bucket, Key), None)


async def test_minio_storage_provider_put_get_head_delete() -> None:
    from server.storage import create_storage_service
    from server.storage.s3_compatible import S3CompatibleStorageProvider

    client = _FakeObjectStorageClient()
    storage = create_storage_service(
        S3CompatibleStorageProvider(
            bucket="octopus",
            client=client,
            provider_id="minio",
        )
    )

    stored = await storage.put_file(
        org_id="org-1",
        namespace="work-products",
        original_filename="report.txt",
        content_type="text/plain",
        body=b"minio object",
    )

    assert stored["provider"] == "minio"
    assert stored["objectKey"].startswith("org-1/work-products/")
    assert client.objects[("octopus", stored["objectKey"])][0] == b"minio object"

    head = await storage.head_object("org-1", stored["objectKey"])
    assert head == {"exists": True, "contentLength": len(b"minio object")}
    assert (
        await storage.get_object_bytes("org-1", stored["objectKey"]) == b"minio object"
    )

    await storage.delete_object("org-1", stored["objectKey"])
    assert ("octopus", stored["objectKey"]) not in client.objects


def test_storage_factory_rejects_incomplete_minio_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.storage import get_storage_service

    monkeypatch.setenv("OCTOPUS_STORAGE_PROVIDER", "minio")
    monkeypatch.delenv("OCTOPUS_STORAGE_BUCKET", raising=False)

    with pytest.raises(ValueError, match="OCTOPUS_STORAGE_BUCKET"):
        get_storage_service()


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


async def test_chat_attachment_multipart_upload_persists_asset_and_hydrates_message(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, _ = app
    org_id, conversation_id, message_id = await _seed_chat(factory)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        upload_response = await client.post(
            f"/api/orgs/{org_id}/chats/{conversation_id}/attachments",
            data={"messageId": message_id},
            files={"file": ("note.txt", b"chat attachment", "text/plain")},
        )
        messages_response = await client.get(f"/api/chats/{conversation_id}/messages")

    assert upload_response.status_code == 201
    attachment = upload_response.json()
    assert attachment["messageId"] == message_id
    assert attachment["contentType"] == "text/plain"
    assert attachment["byteSize"] == len(b"chat attachment")
    assert attachment["originalFilename"] == "note.txt"
    assert attachment["contentPath"] == f"/api/assets/{attachment['assetId']}/content"

    assert messages_response.status_code == 200
    messages = messages_response.json()
    assert messages[0]["attachments"][0]["assetId"] == attachment["assetId"]

    code, headers, body = await _request(application, "GET", attachment["contentPath"])
    assert code == 200
    assert headers["content-type"].startswith("text/plain")
    assert body == b"chat attachment"


async def test_chat_attachment_multipart_upload_rejects_empty_file(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, _ = app
    org_id, conversation_id, message_id = await _seed_chat(factory)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/orgs/{org_id}/chats/{conversation_id}/attachments",
            data={"messageId": message_id},
            files={"file": ("empty.txt", b"", "text/plain")},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "'file' must not be empty"


async def test_issue_attachment_upload_list_download_and_delete(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, _ = app
    org_id, issue_id = await _seed_issue(factory)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        upload_response = await client.post(
            f"/api/orgs/{org_id}/issues/{issue_id}/attachments",
            data={"usage": "evidence"},
            files={"file": ("evidence.txt", b"issue evidence", "text/plain")},
        )
        list_response = await client.get(f"/api/issues/{issue_id}/attachments")

    assert upload_response.status_code == 201
    attachment = upload_response.json()
    assert attachment["issueId"] == issue_id
    assert attachment["usage"] == "evidence"
    assert attachment["contentPath"] == f"/api/assets/{attachment['assetId']}/content"
    assert list_response.status_code == 200
    assert list_response.json() == [attachment]

    code, _, body = await _request(application, "GET", attachment["contentPath"])
    assert code == 200
    assert body == b"issue evidence"

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        delete_response = await client.delete(f"/api/attachments/{attachment['id']}")
    assert delete_response.status_code == 204

    missing_code, _, missing_body = await _request(
        application, "GET", attachment["contentPath"]
    )
    assert missing_code == 404
    assert b"Asset not found" in missing_body


async def test_runtime_work_product_content_is_archived_as_asset(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    from server.services.workspaces import WorkspaceService

    application, factory, _ = app
    org_id, issue_id = await _seed_issue(factory)
    async with factory() as session:
        products = await WorkspaceService(session).persist_run_work_products(
            run_id=str(uuid.uuid4()),
            context_snapshot={"issueId": issue_id},
            products=[
                {
                    "title": "Runtime report",
                    "type": "artifact",
                    "provider": "octopus",
                    "content": "runtime report body",
                    "contentType": "text/plain",
                    "filename": "runtime-report.txt",
                }
            ],
        )
        await session.commit()

    assert len(products) == 1
    product = products[0]
    assert product["orgId"] == org_id
    asset_id = product.get("assetId")
    content_path = product.get("contentPath")
    metadata = product.get("metadata") or {}
    assert asset_id is not None
    assert content_path is not None
    assert content_path == f"/api/assets/{asset_id}/content"
    assert metadata["contentType"] == "text/plain"

    code, headers, body = await _request(application, "GET", content_path)
    assert code == 200
    assert headers["content-type"].startswith("text/plain")
    assert body == b"runtime report body"


async def test_issue_detail_surfaces_work_products_with_asset_content_alongside_attachments(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    from server.services.workspaces import WorkspaceService

    application, factory, _ = app
    org_id, issue_id = await _seed_issue(factory)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        attachment_response = await client.post(
            f"/api/orgs/{org_id}/issues/{issue_id}/attachments",
            data={"usage": "input"},
            files={"file": ("input.txt", b"input attachment", "text/plain")},
        )
    assert attachment_response.status_code == 201
    attachment = attachment_response.json()

    async with factory() as session:
        products = await WorkspaceService(session).persist_run_work_products(
            run_id=str(uuid.uuid4()),
            context_snapshot={"issueId": issue_id},
            products=[
                {
                    "title": "Execution output",
                    "type": "artifact",
                    "provider": "octopus",
                    "content": "execution output body",
                    "contentType": "text/plain",
                    "filename": "execution-output.txt",
                    "summary": "generated by runtime",
                }
            ],
        )
        await session.commit()
    assert len(products) == 1

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        detail_response = await client.get(f"/api/issues/{issue_id}")
        attachments_response = await client.get(f"/api/issues/{issue_id}/attachments")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["workProducts"][0]["title"] == "Execution output"
    assert detail["workProducts"][0]["summary"] == "generated by runtime"
    product_content_path = products[0].get("contentPath")
    assert isinstance(product_content_path, str)
    assert detail["workProducts"][0]["contentPath"] == product_content_path
    assert attachments_response.status_code == 200
    assert attachments_response.json() == [attachment]

    product_code, _, product_body = await _request(
        application, "GET", product_content_path
    )
    attachment_code, _, attachment_body = await _request(
        application, "GET", attachment["contentPath"]
    )
    assert product_code == 200
    assert product_body == b"execution output body"
    assert attachment_code == 200
    assert attachment_body == b"input attachment"
