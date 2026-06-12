from __future__ import annotations

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import server
import server.__main__ as server_module
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


def test_server_command_starts_uvicorn_with_configured_bindings(
    monkeypatch: MonkeyPatch, tmp_path
) -> None:
    recorded: dict[str, object] = {}

    def fake_run(application: str, **kwargs: object) -> None:
        recorded["application"] = application
        recorded.update(kwargs)

    monkeypatch.setenv("OCTOPUS_HOST", "0.0.0.0")
    monkeypatch.setenv("OCTOPUS_PORT", "9123")
    monkeypatch.setenv("OCTOPUS_LOG_LEVEL", "debug")
    monkeypatch.setenv("OCTOPUS_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "octopus-home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "test-instance")
    monkeypatch.setattr("uvicorn.run", fake_run)

    server.main()

    assert recorded == {
        "application": "server.app:app",
        "host": "0.0.0.0",
        "port": 9123,
        "log_level": "debug",
        "timeout_graceful_shutdown": 2,
    }
    assert (
        tmp_path
        / "octopus-home"
        / "instances"
        / "test-instance"
        / "logs"
        / "octopus.log"
    ).exists()


def test_python_module_entrypoint_delegates_to_server_main(
    monkeypatch: MonkeyPatch,
) -> None:
    called: list[str] = []

    def fake_main() -> None:
        called.append("main")

    monkeypatch.setattr(server_module, "main", fake_main)

    server_module.run()

    assert called == ["main"]
