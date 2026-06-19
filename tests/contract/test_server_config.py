from __future__ import annotations

from pathlib import Path

import pytest

from server.config import Settings


def test_default_database_url_does_not_use_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("OCTOPUS_HOME", raising=False)
    monkeypatch.delenv("OCTOPUS_INSTANCE_ID", raising=False)
    monkeypatch.delenv("OCTOPUS_DATABASE_URL", raising=False)

    settings = Settings.from_env()

    database_path = (
        tmp_path / ".octopus" / "instances" / "default" / "db" / "octopus.db"
    ).resolve()
    assert settings.database_url == f"sqlite+aiosqlite:///{database_path.as_posix()}"
    assert (
        settings.database_url
        != f"sqlite+aiosqlite:///{(Path.cwd() / 'octopus.db').as_posix()}"
    )


def test_database_url_env_override_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'custom.db').as_posix()}"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", database_url)

    assert Settings.from_env().database_url == database_url


def test_graceful_shutdown_timeout_defaults_to_five_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCTOPUS_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", raising=False)

    assert Settings.from_env().graceful_shutdown_timeout_seconds == 5


def test_graceful_shutdown_timeout_env_override_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", "2")

    assert Settings.from_env().graceful_shutdown_timeout_seconds == 2
