from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
from packages.database.queries.agent_state import (
    delete_task_sessions,
    update_runtime_state,
)
from packages.database.queries.approvals import update_approval
from packages.database.queries.goals import delete_goal, update_goal
from packages.database.queries.heartbeat import (
    claim_queued_run,
    update_run,
    update_wakeup_request,
)
from packages.database.queries.organization_skills import (
    delete_organization_skill,
    update_organization_skill,
)
from packages.database.queries.organizations import increment_issue_counter
from packages.database.queries.projects import delete_project, update_project
from packages.database.queries.resources import (
    delete_organization_resource,
    delete_project_resource_attachment,
    update_organization_resource,
    update_project_resource_attachment,
)
from packages.database.queries.runtime_providers import (
    create_global_runtime_provider,
    delete_global_runtime_provider,
    update_global_runtime_provider,
)
from packages.database.queries.workspaces import (
    delete_project_workspace,
    update_execution_workspace,
    update_project_workspace,
    update_workspace_operation,
    update_workspace_runtime_service,
)
from packages.database.schema import (
    Agent,
    Approval,
    AgentRuntimeState,
    AgentTaskSession,
    AgentWakeupRequest,
    Base,
    ExecutionWorkspace,
    Goal,
    HeartbeatRun,
    Organization,
    OrganizationResource,
    OrganizationSkill,
    Project,
    ProjectResourceAttachment,
    ProjectWorkspace,
    RuntimeGlobalProvider,
    WorkspaceOperation,
    WorkspaceRuntimeService,
)
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


def test_alembic_cli_uses_octopus_database_url_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "cli-env" / "octopus.db"
    monkeypatch.setenv(
        "OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}"
    )

    command.current(Config("alembic.ini"))

    assert db_path.is_file()


def test_alembic_cli_without_database_url_uses_instance_sqlite_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "dev")
    monkeypatch.delenv("OCTOPUS_DATABASE_URL", raising=False)

    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option(
        "script_location", str(project_root / "packages" / "database" / "migrations")
    )
    command.current(config)

    expected = tmp_path / "home" / "instances" / "dev" / "db" / "octopus.db"
    assert expected.is_file()
    assert not (cwd / "octopus.db").exists()


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
    approval = Approval(
        id="approval-1",
        org_id="org-1",
        type="hire_agent",
        status="pending",
        payload={"agentId": "agent-1"},
    )

    async with session_factory() as session:
        session.add_all([org, agent, skill, approval])
        await session.commit()

    async with session_factory() as session:
        updated_agent = await update_agent(session, "agent-1", {"name": "New Agent"})
        updated_skill = await update_organization_skill(
            session,
            "org-1",
            "skill-1",
            {"name": "Deep Review"},
        )
        updated_approval = await update_approval(
            session,
            "approval-1",
            {"status": "approved", "decision_note": "ship it"},
        )
        counter = await increment_issue_counter(session, "org-1")
        await session.commit()

    assert updated_agent is not None
    assert updated_agent.name == "New Agent"
    assert updated_skill is not None
    assert updated_skill.name == "Deep Review"
    assert updated_approval is not None
    assert updated_approval.status == "approved"
    assert updated_approval.decision_note == "ship it"
    assert updated_approval.decided_at is not None
    assert counter == (1, "ORG")


async def test_returning_fallback_updates_project_goal_and_resource_rows(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_compat, "supports_update_returning", lambda _: False)
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
        session.add(Project(id="project-1", org_id="org-1", name="Project 1"))
        session.add(Goal(id="goal-1", org_id="org-1", title="Goal 1", level="task"))
        session.add(
            OrganizationResource(
                id="resource-1",
                org_id="org-1",
                name="Runbook",
                kind="doc",
                locator="file://runbook.md",
            )
        )
        session.add(
            ProjectResourceAttachment(
                id="attachment-1",
                org_id="org-1",
                project_id="project-1",
                resource_id="resource-1",
                role="reference",
            )
        )
        await session.commit()

    async with session_factory() as session:
        project = await update_project(session, "project-1", {"name": "Project 2"})
        goal = await update_goal(session, "goal-1", {"title": "Goal 2"})
        resource = await update_organization_resource(
            session, "org-1", "resource-1", {"name": "Runbook 2"}
        )
        attachment = await update_project_resource_attachment(
            session, "attachment-1", {"role": "primary"}
        )
        await session.commit()

    assert project is not None
    assert project.name == "Project 2"
    assert goal is not None
    assert goal.title == "Goal 2"
    assert resource is not None
    assert resource.name == "Runbook 2"
    assert attachment is not None
    assert attachment.role == "primary"

    async with session_factory() as session:
        deleted_attachment = await delete_project_resource_attachment(
            session, "attachment-1"
        )
        deleted_resource = await delete_organization_resource(
            session, "org-1", "resource-1"
        )
        deleted_goal = await delete_goal(session, "goal-1")
        deleted_project = await delete_project(session, "project-1")
        await session.commit()

    assert deleted_attachment is not None
    assert deleted_attachment.id == "attachment-1"
    assert deleted_resource is not None
    assert deleted_resource.id == "resource-1"
    assert deleted_goal is not None
    assert deleted_goal.id == "goal-1"
    assert deleted_project is not None
    assert deleted_project.id == "project-1"


async def test_returning_fallback_updates_heartbeat_and_agent_state_rows(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_compat, "supports_update_returning", lambda _: False)
    monkeypatch.setattr(_compat, "supports_delete_returning", lambda _: False)
    started_at = datetime.now(UTC)

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
            Agent(
                id="agent-1",
                org_id="org-1",
                name="Agent 1",
                workspace_key="agent-1",
                role="general",
                agent_runtime_type="codex_local",
                agent_runtime_config={},
            )
        )
        session.add(
            AgentWakeupRequest(
                id="wakeup-1",
                org_id="org-1",
                agent_id="agent-1",
                source="manual",
                status="queued",
            )
        )
        session.add(
            HeartbeatRun(
                id="run-1",
                org_id="org-1",
                agent_id="agent-1",
                invocation_source="manual",
                status="queued",
            )
        )
        session.add(
            AgentRuntimeState(
                agent_id="agent-1",
                org_id="org-1",
                agent_runtime_type="codex_local",
                state_json={},
            )
        )
        session.add_all(
            [
                AgentTaskSession(
                    id="task-session-1",
                    org_id="org-1",
                    agent_id="agent-1",
                    agent_runtime_type="codex_local",
                    task_key="task-1",
                ),
                AgentTaskSession(
                    id="task-session-2",
                    org_id="org-1",
                    agent_id="agent-1",
                    agent_runtime_type="codex_local",
                    task_key="task-2",
                ),
            ]
        )
        await session.commit()

    async with session_factory() as session:
        wakeup = await update_wakeup_request(session, "wakeup-1", {"status": "claimed"})
        claimed = await claim_queued_run(session, "run-1", started_at)
        assert claimed is not None
        assert claimed.status == "running"
        run = await update_run(session, "run-1", {"status": "succeeded"})
        state = await update_runtime_state(
            session,
            "agent-1",
            {"last_run_id": "run-1", "last_run_status": "succeeded"},
        )
        deleted_count = await delete_task_sessions(
            session, org_id="org-1", agent_id="agent-1"
        )
        await session.commit()

    assert wakeup is not None
    assert wakeup.status == "claimed"
    assert run is not None
    assert run.status == "succeeded"
    assert state is not None
    assert state.last_run_status == "succeeded"
    assert deleted_count == 2


async def test_returning_fallback_updates_workspace_rows(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_compat, "supports_update_returning", lambda _: False)
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
            Agent(
                id="agent-1",
                org_id="org-1",
                name="Agent 1",
                workspace_key="agent-1",
                role="general",
                agent_runtime_type="codex_local",
                agent_runtime_config={},
            )
        )
        session.add(Project(id="project-1", org_id="org-1", name="Project 1"))
        session.add(
            ProjectWorkspace(
                id="project-workspace-1",
                org_id="org-1",
                project_id="project-1",
                name="Local",
                source_type="local_path",
                visibility="default",
                is_primary=True,
            )
        )
        session.add(
            ExecutionWorkspace(
                id="execution-workspace-1",
                org_id="org-1",
                project_id="project-1",
                project_workspace_id="project-workspace-1",
                mode="shared",
                strategy_type="reuse",
                name="Execution",
                status="active",
                provider_type="local_fs",
            )
        )
        session.add(
            WorkspaceRuntimeService(
                id="runtime-service-1",
                org_id="org-1",
                project_id="project-1",
                project_workspace_id="project-workspace-1",
                execution_workspace_id="execution-workspace-1",
                scope_type="workspace",
                service_name="dev",
                status="running",
                lifecycle="manual",
                provider="process",
            )
        )
        session.add(
            WorkspaceOperation(
                id="operation-1",
                org_id="org-1",
                execution_workspace_id="execution-workspace-1",
                phase="setup",
                status="running",
            )
        )
        await session.commit()

    async with session_factory() as session:
        project_workspace = await update_project_workspace(
            session, "project-workspace-1", {"name": "Local 2"}
        )
        execution_workspace = await update_execution_workspace(
            session, "execution-workspace-1", {"status": "idle"}
        )
        runtime_service = await update_workspace_runtime_service(
            session, "runtime-service-1", {"status": "stopped"}
        )
        operation = await update_workspace_operation(
            session, "operation-1", {"status": "succeeded"}
        )
        await session.commit()

    assert project_workspace is not None
    assert project_workspace.name == "Local 2"
    assert execution_workspace is not None
    assert execution_workspace.status == "idle"
    assert runtime_service is not None
    assert runtime_service.status == "stopped"
    assert operation is not None
    assert operation.status == "succeeded"

    async with session_factory() as session:
        deleted_workspace = await delete_project_workspace(
            session, "project-workspace-1"
        )
        await session.commit()

    assert deleted_workspace is not None
    assert deleted_workspace.id == "project-workspace-1"


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


async def test_runtime_provider_writes_do_not_require_returning(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_compat, "supports_update_returning", lambda _: False)
    monkeypatch.setattr(_compat, "supports_delete_returning", lambda _: False)

    async with session_factory() as session:
        created = await create_global_runtime_provider(
            session,
            {
                "id": "provider-1",
                "runtime_type": "codex_local",
                "provider_id": "openai",
                "name": "OpenAI",
                "protocol": "openai",
                "config_json": {},
            },
        )
        await session.commit()

    assert created.created_at is not None
    assert created.updated_at is not None

    async with session_factory() as session:
        updated = await update_global_runtime_provider(
            session,
            "codex_local",
            "openai",
            {"name": "OpenAI Global"},
        )
        await session.commit()

    assert updated is not None
    assert updated.name == "OpenAI Global"

    async with session_factory() as session:
        deleted = await delete_global_runtime_provider(session, "codex_local", "openai")
        await session.commit()

    assert deleted is not None
    assert deleted.id == "provider-1"

    async with session_factory() as session:
        remaining = await session.get(RuntimeGlobalProvider, "provider-1")

    assert remaining is None
