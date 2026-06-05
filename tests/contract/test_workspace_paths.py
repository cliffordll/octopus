from __future__ import annotations

from pathlib import Path

import pytest

from server.services.workspace_paths import (
    ensure_organization_workspace_root,
    organization_workspace_relative_path,
    organization_workspace_root,
    resolve_octopus_home_dir,
    resolve_octopus_instance_root,
)


def test_organization_workspace_uses_octopus_instance_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")

    assert resolve_octopus_home_dir() == (tmp_path / "home").resolve()
    assert (
        resolve_octopus_instance_root()
        == (tmp_path / "home" / "instances" / "dev").resolve()
    )
    assert organization_workspace_relative_path("org-1") == (
        "organizations/org-1/workspaces"
    )
    assert (
        organization_workspace_root("org-1")
        == (
            tmp_path
            / "home"
            / "instances"
            / "dev"
            / "organizations"
            / "org-1"
            / "workspaces"
        ).resolve()
    )


def test_octopus_home_defaults_next_to_sqlite_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OCTOPUS_HOME", raising=False)
    monkeypatch.delenv("OCTOPUS_DATABASE_URL", raising=False)
    monkeypatch.delenv("OCTOPUS_INSTANCE_ID", raising=False)

    assert resolve_octopus_home_dir() == (tmp_path / ".octopus").resolve()
    assert (
        resolve_octopus_instance_root()
        == (tmp_path / ".octopus" / "instances" / "default").resolve()
    )


def test_octopus_home_defaults_next_to_configured_sqlite_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "data" / "octopus.db"
    monkeypatch.delenv("OCTOPUS_HOME", raising=False)
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    assert resolve_octopus_home_dir() == (db_path.parent / ".octopus").resolve()


def test_octopus_home_expands_user_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("OCTOPUS_HOME", "~/.octopus-dev")
    monkeypatch.delenv("OCTOPUS_INSTANCE_ID", raising=False)

    assert resolve_octopus_home_dir() == (tmp_path / ".octopus-dev").resolve()
    assert (
        resolve_octopus_instance_root()
        == (tmp_path / ".octopus-dev" / "instances" / "default").resolve()
    )


def test_octopus_home_env_overrides_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(
        "OCTOPUS_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'data' / 'octopus.db'}",
    )

    assert resolve_octopus_home_dir() == (tmp_path / "home").resolve()


def test_octopus_instance_id_rejects_path_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "../bad")

    with pytest.raises(ValueError, match="Invalid OCTOPUS_INSTANCE_ID"):
        resolve_octopus_instance_root()


def test_ensure_organization_workspace_migrates_legacy_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")

    legacy_root = tmp_path / "home" / "organizations" / "org-1" / "workspaces"
    legacy_agent = legacy_root / "agents" / "agent-1" / "instructions" / "SOUL.md"
    legacy_agent.parent.mkdir(parents=True)
    legacy_agent.write_text("# Soul\n", encoding="utf-8")

    canonical_root = ensure_organization_workspace_root("org-1")

    assert canonical_root == organization_workspace_root("org-1")
    assert (
        canonical_root / "agents" / "agent-1" / "instructions" / "SOUL.md"
    ).read_text(encoding="utf-8") == "# Soul\n"
    assert not legacy_agent.exists()
