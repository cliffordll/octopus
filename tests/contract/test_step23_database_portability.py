from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TypeGuard

from alembic import command
from alembic.config import Config
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


def test_alembic_cli_uses_octopus_database_url_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "cli-env" / "octopus.db"
    monkeypatch.setenv(
        "OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}"
    )

    command.current(Config("alembic.ini"))

    assert db_path.is_file()


async def test_asyncmy_terminate_uses_force_close_for_invalidated_connections() -> None:
    class FakeAsyncmyConnection:
        def __init__(self) -> None:
            self.force_close_called = False
            self.terminate_called = False

        def _terminate_force_close(self) -> None:
            self.force_close_called = True

        def terminate(self) -> None:
            self.terminate_called = True
            raise AssertionError("graceful asyncmy terminate should not be used")

    engine = create_database_engine(
        "mysql+asyncmy://user:pass@127.0.0.1:3306/octopus?charset=utf8mb4"
    )
    connection = FakeAsyncmyConnection()
    try:
        engine.sync_engine.dialect.do_terminate(connection)  # type: ignore[arg-type]
    finally:
        await engine.dispose()

    assert connection.force_close_called
    assert not connection.terminate_called


def test_alembic_config_database_url_overrides_instance_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "explicit-config" / "octopus.db"
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")
    monkeypatch.delenv("OCTOPUS_DATABASE_URL", raising=False)

    command.current(_build_config(f"sqlite+aiosqlite:///{db_path.as_posix()}"))

    default_path = tmp_path / "home" / "instances" / "dev" / "db" / "octopus.db"
    assert db_path.is_file()
    assert not default_path.exists()


def test_baseline_mysql_text_indexes_use_prefix_lengths() -> None:
    migration_paths = Path("packages/database/migrations/versions").glob("*.py")
    missing_prefix_lengths: list[tuple[str, str, str, tuple[str, ...]]] = []
    text_unique_constraints: list[tuple[str, str, str, tuple[str, ...]]] = []

    for migration_path in migration_paths:
        tree = ast.parse(migration_path.read_text(encoding="utf-8"))
        table_text_columns: dict[str, set[str]] = {}

        for node in ast.walk(tree):
            if not _is_op_call(node, "create_table"):
                continue
            table_name = _constant_arg(node, 0)
            if table_name is None:
                continue
            table_text_columns[table_name] = _text_columns_from_create_table(node)
            text_unique_constraints.extend(
                _text_unique_constraints(
                    migration_path, table_name, node, table_text_columns[table_name]
                )
            )

        for node in ast.walk(tree):
            if not _is_op_call(node, "create_index"):
                continue
            index_name = _constant_arg(node, 0)
            table_name = _constant_arg(node, 1)
            column_names = _list_arg(node, 2)
            if index_name is None or table_name is None or column_names is None:
                continue
            indexed_text_columns = tuple(
                column_name
                for column_name in column_names
                if column_name in table_text_columns.get(table_name, set())
            )
            if not indexed_text_columns:
                continue
            if _has_keyword(node, "mysql_length"):
                continue
            if (
                migration_path.name == "20260526_000001_baseline.py"
                and index_name == "issues_open_automation_execution_uq"
            ):
                continue
            missing_prefix_lengths.append(
                (migration_path.name, table_name, index_name, indexed_text_columns)
            )

    assert missing_prefix_lengths == []
    assert text_unique_constraints == []


def test_migration_identifiers_fit_mysql_limit() -> None:
    migration_paths = Path("packages/database/migrations/versions").glob("*.py")
    long_identifiers: list[tuple[str, str, int]] = []

    for migration_path in migration_paths:
        tree = ast.parse(migration_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            identifier = _migration_identifier(node)
            if identifier is not None and len(identifier) > 64:
                long_identifiers.append(
                    (migration_path.name, identifier, len(identifier))
                )

    assert long_identifiers == []


def test_runtime_scope_migration_renames_mysql_indexes() -> None:
    migration_path = Path(
        "packages/database/migrations/versions/"
        "20260607_000018_runtime_provider_scope.py"
    )
    source = migration_path.read_text(encoding="utf-8")

    assert "RENAME INDEX" in source
    assert "def _downgrade_renamed_runtime_tables" in source
    assert 'if op.get_bind().dialect.name == "mysql"' in source


def _migration_identifier(node: ast.Call) -> str | None:
    if not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr in {"create_index", "drop_index"}:
        return _constant_arg(node, 0)
    if node.func.attr not in {
        "ForeignKeyConstraint",
        "PrimaryKeyConstraint",
        "UniqueConstraint",
    }:
        return None
    for keyword in node.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, str):
                return keyword.value.value
    return None


def _is_op_call(node: ast.AST, function_name: str) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == function_name
    )


def _constant_arg(node: ast.Call, index: int) -> str | None:
    if len(node.args) <= index:
        return None
    arg = node.args[index]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def _list_arg(node: ast.Call, index: int) -> tuple[str, ...] | None:
    if len(node.args) <= index:
        return None
    arg = node.args[index]
    if not isinstance(arg, ast.List):
        return None
    values: list[str] = []
    for item in arg.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        values.append(item.value)
    return tuple(values)


def _has_keyword(node: ast.Call, keyword_name: str) -> bool:
    return any(keyword.arg == keyword_name for keyword in node.keywords)


def _text_columns_from_create_table(node: ast.Call) -> set[str]:
    text_columns: set[str] = set()
    for arg in node.args[1:]:
        if not _is_column_call(arg):
            continue
        column_name = _constant_arg(arg, 0)
        if column_name is None:
            continue
        if len(arg.args) > 1 and _is_type_call(arg.args[1], "Text"):
            text_columns.add(column_name)
    return text_columns


def _text_unique_constraints(
    migration_path: Path,
    table_name: str,
    create_table_call: ast.Call,
    text_columns: set[str],
) -> list[tuple[str, str, str, tuple[str, ...]]]:
    constraints: list[tuple[str, str, str, tuple[str, ...]]] = []
    for arg in create_table_call.args[1:]:
        if not _is_type_call(arg, "UniqueConstraint"):
            continue
        column_names = tuple(
            item.value
            for item in arg.args
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
        indexed_text_columns = tuple(
            column_name for column_name in column_names if column_name in text_columns
        )
        if indexed_text_columns:
            constraints.append(
                (
                    migration_path.name,
                    table_name,
                    _constraint_name(arg),
                    indexed_text_columns,
                )
            )
    return constraints


def _is_column_call(node: ast.AST) -> TypeGuard[ast.Call]:
    return _is_type_call(node, "Column")


def _is_type_call(node: ast.AST, type_name: str) -> TypeGuard[ast.Call]:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == type_name
    )


def _constraint_name(node: ast.Call) -> str:
    for keyword in node.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, str):
                return keyword.value.value
    return "<unnamed>"


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
