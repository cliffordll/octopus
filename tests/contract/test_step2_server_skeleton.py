from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from server.app import app


def test_app_registers_orgs_route() -> None:
    paths = {route.path for route in app.router.routes if isinstance(route, APIRoute)}
    assert "/api/orgs" in paths


def test_orgs_route_requires_actor_context() -> None:
    client = TestClient(app)

    response = client.get("/api/orgs")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Actor context is not configured for board-scoped org listing"
    }
