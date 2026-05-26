from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_lifespan_auto_creates_schema_on_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With auto-migrate enabled, startup should upgrade an empty DB before requests."""
    db_path = tmp_path / "test_lifespan_bootstrap.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OCTOPUS_POD_ID", "test-pod")
    monkeypatch.setenv("OCTOPUS_AUTO_MIGRATE", "1")

    from server.app import create_app

    fresh_app = create_app()

    with TestClient(fresh_app) as client:
        response = client.get(f"/api/orgs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Organization not found"


def test_lifespan_does_not_create_schema_without_auto_migrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "test_lifespan_no_auto_migrate.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("OCTOPUS_POD_ID", "test-pod")
    monkeypatch.delenv("OCTOPUS_AUTO_MIGRATE", raising=False)

    from server.app import create_app

    fresh_app = create_app()

    with TestClient(fresh_app, raise_server_exceptions=False) as client:
        response = client.get(f"/api/orgs/{uuid.uuid4()}")

    assert response.status_code == 500
