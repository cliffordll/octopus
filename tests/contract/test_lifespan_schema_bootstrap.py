from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_lifespan_auto_creates_schema_on_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: before fix, starting server against an empty sqlite file
    returned 500 'no such table: organization_ownership' on any DB-touching
    request because lifespan never created the schema.
    """
    db_path = tmp_path / "test_lifespan_bootstrap.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OCTOPUS_POD_ID", "test-pod")

    from server.app import create_app

    fresh_app = create_app()

    with TestClient(fresh_app) as client:
        response = client.get(f"/api/orgs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"
