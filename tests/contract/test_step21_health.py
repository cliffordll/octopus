from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from server.app import app


def test_health_route_registered() -> None:
    paths = {route.path for route in app.router.routes if isinstance(route, APIRoute)}
    assert "/api/health" in paths


def test_health_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
