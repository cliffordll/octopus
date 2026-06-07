from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.migrations.runner import _build_config
from packages.database.queries import _compat
from packages.database.queries.agents import update_agent
from packages.database.queries.organization_skills import (
    delete_organization_skill,
    update_organization_skill,
)
from packages.database.queries.organizations import increment_issue_counter
from packages.database.schema import Agent, Base, Organization, OrganizationSkill
from packages.runtimes.paths import (
    ensure_managed_runtime_home,
    resolve_octopus_home_dir as resolve_runtime_octopus_home_dir,
)
from server.config import Settings


async def test_engine_factory_creates_sqlite_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "home" / "instances" / "dev" / "db" / "octopus.db"

    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        assert db_path.parent.is_dir()
    finally:
        await engine.dispose()


def test_migration_runner_creates_sqlite_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "home" / "instances" / "dev" / "db" / "octopus.db"

    _build_config(f"sqlite+aiosqlite:///{db_path.as_posix()}")

    assert db_path.parent.is_dir()


def test_settings_default_database_url_uses_instance_sqlite_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")
    monkeypatch.delenv("OCTOPUS_DATABASE_URL", raising=False)

    settings = Settings.from_env()

    expected = tmp_path / "home" / "instances" / "dev" / "db" / "octopus.db"
    assert settings.database_url == f"sqlite+aiosqlite:///{expected.as_posix()}"


def test_runtime_paths_default_to_user_octopus_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "user-home")
    monkeypatch.delenv("OCTOPUS_HOME", raising=False)
    monkeypatch.delenv("OCTOPUS_INSTANCE_ID", raising=False)

    assert (
        resolve_runtime_octopus_home_dir()
        == (tmp_path / "user-home" / ".octopus").resolve()
    )


def test_runtime_home_migrates_legacy_runtime_homes_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")
    legacy_config = (
        tmp_path
        / "home"
        / "runtime-homes"
        / "opencode_local"
        / "org-1"
        / "agent-1"
        / "home"
        / ".config"
        / "opencode"
        / "opencode.json"
    )
    legacy_config.parent.mkdir(parents=True)
    legacy_config.write_text('{"provider":{}}\n', encoding="utf-8")

    runtime_home = ensure_managed_runtime_home(
        "opencode_local", org_id="org-1", agent_id="agent-1"
    )

    expected_home = (
        tmp_path
        / "home"
        / "instances"
        / "dev"
        / "organizations"
        / "org-1"
        / "opencode-home"
    ).resolve()
    expected_config = expected_home / "home" / ".config" / "opencode" / "opencode.json"
    assert runtime_home == expected_home
    assert expected_config.read_text(encoding="utf-8") == '{"provider":{}}\n'
    assert not legacy_config.exists()


def test_runtime_home_migrates_instance_runtime_homes_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")
    legacy_config = (
        tmp_path
        / "home"
        / "instances"
        / "dev"
        / "runtime-homes"
        / "codex_local"
        / "org-1"
        / "agent-1"
        / "config.json"
    )
    legacy_config.parent.mkdir(parents=True)
    legacy_config.write_text('{"model":"test"}\n', encoding="utf-8")

    runtime_home = ensure_managed_runtime_home(
        "codex_local", org_id="org-1", agent_id="agent-1"
    )

    expected_home = (
        tmp_path
        / "home"
        / "instances"
        / "dev"
        / "organizations"
        / "org-1"
        / "codex-home"
        / "agents"
        / "agent-1"
    ).resolve()
    assert runtime_home == expected_home
    assert (expected_home / "config.json").read_text(encoding="utf-8") == (
        '{"model":"test"}\n'
    )
    assert not legacy_config.exists()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


async def test_returning_fallback_updates_core_write_rows(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_compat, "supports_update_returning", lambda _: False)
    org = Organization(
        id="org-1",
        url_key="org-1",
        name="Org 1",
        issue_prefix="ORG",
    )
    agent = Agent(
        id="agent-1",
        org_id="org-1",
        name="Original Agent",
        workspace_key="agent-1",
        role="general",
        agent_runtime_type="codex_local",
        agent_runtime_config={},
    )
    skill = OrganizationSkill(
        id="skill-1",
        org_id="org-1",
        key="review",
        slug="review",
        name="Review",
        markdown="Review code.",
    )

    async with session_factory() as session:
        session.add_all([org, agent, skill])
        await session.commit()

    async with session_factory() as session:
        updated_agent = await update_agent(session, "agent-1", {"name": "New Agent"})
        updated_skill = await update_organization_skill(
            session,
            "org-1",
            "skill-1",
            {"name": "Deep Review"},
        )
        counter = await increment_issue_counter(session, "org-1")
        await session.commit()

    assert updated_agent is not None
    assert updated_agent.name == "New Agent"
    assert updated_skill is not None
    assert updated_skill.name == "Deep Review"
    assert counter == (1, "ORG")


async def test_returning_fallback_deletes_core_write_rows(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_compat, "supports_delete_returning", lambda _: False)

    async with session_factory() as session:
        session.add(
            Organization(
                id="org-1",
                url_key="org-1",
                name="Org 1",
                issue_prefix="ORG",
            )
        )
        session.add(
            OrganizationSkill(
                id="skill-1",
                org_id="org-1",
                key="review",
                slug="review",
                name="Review",
                markdown="Review code.",
            )
        )
        await session.commit()

    async with session_factory() as session:
        deleted = await delete_organization_skill(session, "org-1", "skill-1")
        await session.commit()

    assert deleted is not None
    assert deleted.id == "skill-1"
