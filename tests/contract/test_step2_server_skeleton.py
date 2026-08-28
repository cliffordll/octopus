from __future__ import annotations

import asyncio
from dataclasses import replace
import logging

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import server
import server.__main__ as server_module
from server.app import app
from server.app_logging import _CancelledSqliteTerminateFilter


def test_app_registers_orgs_route() -> None:
    paths = {route.path for route in app.router.routes if isinstance(route, APIRoute)}
    assert "/api/orgs" in paths


def test_orgs_route_requires_actor_context() -> None:
    app.state.settings = replace(app.state.settings, local_trusted=False)
    client = TestClient(app)

    response = client.get("/api/orgs")

    assert response.status_code == 503
    assert response.json() == {"detail": "Actor context is not configured"}


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


def test_sqlalchemy_pool_cancelled_termination_log_is_filtered() -> None:
    filter_item = _CancelledSqliteTerminateFilter()
    cancelled_record = logging.LogRecord(
        "sqlalchemy.pool.impl.AsyncAdaptedQueuePool",
        logging.ERROR,
        __file__,
        1,
        "Exception terminating connection %r",
        ("connection",),
        (asyncio.CancelledError, asyncio.CancelledError("cancelled"), None),
    )
    runtime_record = logging.LogRecord(
        "sqlalchemy.pool.impl.AsyncAdaptedQueuePool",
        logging.ERROR,
        __file__,
        1,
        "Exception terminating connection %r",
        ("connection",),
        (RuntimeError, RuntimeError("database failed"), None),
    )

    assert filter_item.filter(cancelled_record) is False
    assert filter_item.filter(runtime_record) is True
