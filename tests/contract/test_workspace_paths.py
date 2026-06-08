from __future__ import annotations

from pathlib import Path

import pytest

from server.services.workspace_paths import (
    ensure_organization_workspace_root,
    ensure_octopus_run_log_dir,
    ensure_octopus_storage_dir,
    ensure_octopus_workspace_operation_log_dir,
    organization_workspace_relative_path,
    organization_workspace_root,
    resolve_default_sqlite_database_url,
    resolve_octopus_database_dir,
    resolve_octopus_home_dir,
    resolve_octopus_instance_root,
    resolve_octopus_run_log_dir,
    resolve_octopus_sqlite_database_path,
    resolve_octopus_storage_dir,
    resolve_octopus_workspace_operation_log_dir,
)


def test_default_database_uses_instance_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("OCTOPUS_HOME", raising=False)
    monkeypatch.delenv("OCTOPUS_INSTANCE_ID", raising=False)
    monkeypatch.delenv("OCTOPUS_DATABASE_URL", raising=False)

    database_path = (
        tmp_path / ".octopus" / "instances" / "default" / "db" / "octopus.db"
    ).resolve()

    assert resolve_octopus_home_dir() == (tmp_path / ".octopus").resolve()
    assert resolve_octopus_database_dir() == database_path.parent
    assert resolve_octopus_sqlite_database_path() == database_path
    assert resolve_default_sqlite_database_url() == (
        f"sqlite+aiosqlite:///{database_path.as_posix()}"
    )
    assert database_path.parent.is_dir()
    assert resolve_octopus_sqlite_database_path() != (Path.cwd() / "octopus.db")


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


def test_instance_scoped_storage_and_workspace_operation_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")
    monkeypatch.delenv("OCTOPUS_STORAGE_DIR", raising=False)
    monkeypatch.delenv("OCTOPUS_WORKSPACE_OPERATION_LOG_DIR", raising=False)

    assert (
        resolve_octopus_storage_dir()
        == (tmp_path / "home" / "instances" / "dev" / "data" / "storage").resolve()
    )
    assert (
        resolve_octopus_workspace_operation_log_dir()
        == (
            tmp_path
            / "home"
            / "instances"
            / "dev"
            / "logs"
            / "workspace-operation-logs"
        ).resolve()
    )


def test_storage_and_workspace_operation_log_env_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_STORAGE_DIR", str(tmp_path / "custom-storage"))
    monkeypatch.setenv(
        "OCTOPUS_WORKSPACE_OPERATION_LOG_DIR", str(tmp_path / "custom-operation-logs")
    )

    assert resolve_octopus_storage_dir() == (tmp_path / "custom-storage").resolve()
    assert (
        resolve_octopus_workspace_operation_log_dir()
        == (tmp_path / "custom-operation-logs").resolve()
    )


def test_storage_and_workspace_operation_logs_migrate_legacy_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")
    monkeypatch.delenv("OCTOPUS_STORAGE_DIR", raising=False)
    monkeypatch.delenv("OCTOPUS_WORKSPACE_OPERATION_LOG_DIR", raising=False)

    legacy_storage_file = tmp_path / "home" / "storage" / "assets" / "file.txt"
    legacy_storage_file.parent.mkdir(parents=True)
    legacy_storage_file.write_text("asset\n", encoding="utf-8")
    legacy_log_file = tmp_path / "home" / "workspace-operation-logs" / "workspace.log"
    legacy_log_file.parent.mkdir(parents=True)
    legacy_log_file.write_text("operation\n", encoding="utf-8")

    storage_dir = ensure_octopus_storage_dir()
    operation_log_dir = ensure_octopus_workspace_operation_log_dir()

    assert storage_dir == resolve_octopus_storage_dir()
    assert operation_log_dir == resolve_octopus_workspace_operation_log_dir()
    assert (storage_dir / "assets" / "file.txt").read_text(encoding="utf-8") == (
        "asset\n"
    )
    assert (operation_log_dir / "workspace.log").read_text(encoding="utf-8") == (
        "operation\n"
    )
    assert not legacy_storage_file.exists()
    assert not legacy_log_file.exists()


def test_run_logs_migrate_legacy_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")
    monkeypatch.delenv("OCTOPUS_RUN_LOG_DIR", raising=False)

    legacy_log = tmp_path / "home" / "run-logs" / "org-1" / "run.log"
    legacy_log.parent.mkdir(parents=True)
    legacy_log.write_text("run\n", encoding="utf-8")

    run_log_dir = ensure_octopus_run_log_dir()

    assert run_log_dir == resolve_octopus_run_log_dir()
    assert (run_log_dir / "org-1" / "run.log").read_text(encoding="utf-8") == "run\n"
    assert not legacy_log.exists()


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


def test_ensure_organization_workspace_migrates_instance_workspaces_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")

    legacy_root = tmp_path / "home" / "instances" / "dev" / "workspaces"
    legacy_artifact = legacy_root / "artifacts" / "report.md"
    legacy_artifact.parent.mkdir(parents=True)
    legacy_artifact.write_text("# Report\n", encoding="utf-8")

    canonical_root = ensure_organization_workspace_root("org-1")

    assert canonical_root == organization_workspace_root("org-1")
    assert (canonical_root / "artifacts" / "report.md").read_text(
        encoding="utf-8"
    ) == "# Report\n"
    assert not legacy_artifact.exists()


def test_ensure_organization_workspace_does_not_merge_instance_org_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")

    legacy_other_org = (
        tmp_path
        / "home"
        / "instances"
        / "dev"
        / "workspaces"
        / "other-org"
        / "artifacts"
        / "report.md"
    )
    legacy_other_org.parent.mkdir(parents=True)
    legacy_other_org.write_text("# Other\n", encoding="utf-8")

    canonical_root = ensure_organization_workspace_root("org-1")

    assert canonical_root == organization_workspace_root("org-1")
    assert not (canonical_root / "other-org" / "artifacts" / "report.md").exists()
    assert legacy_other_org.read_text(encoding="utf-8") == "# Other\n"
