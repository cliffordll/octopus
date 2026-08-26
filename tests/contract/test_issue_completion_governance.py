from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import (
    ActivityLog,
    Agent,
    Base,
    HeartbeatRun,
    Issue,
    IssueWorkProduct,
    Organization,
)
from server.services.issue_completion import IssueCompletionGovernance
from server.services.heartbeat import HeartbeatService
from server.services.issues import IssueService


@pytest.mark.parametrize(
    "runtime_type", ["codex_local", "claude_local", "opencode_local"]
)
async def test_declared_outputs_are_validated_for_every_runtime(
    runtime_type: str,
    tmp_path: Path,
) -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                name=f"{runtime_type} outputs",
                url_key=f"{runtime_type}-outputs",
                issue_prefix="OUT",
            )
            session.add(org)
            await session.flush()
            agent = Agent(
                org_id=org.id,
                name=f"{runtime_type} agent",
                agent_runtime_type=runtime_type,
            )
            session.add(agent)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                title="Create a report",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            session.add(issue)
            await session.flush()
            workspace = tmp_path / runtime_type
            workspace.mkdir()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={
                    "issueId": issue.id,
                    "workspace": {"octopusWorkspace": {"cwd": str(workspace)}},
                },
            )
            session.add(run)
            await session.flush()
            issue.execution_run_id = run.id
            issue.checkout_run_id = run.id
            await session.flush()

            updated = await IssueService(session).update_issue(
                issue.id,
                {
                    "status": "done",
                    "comment": "Report completed.",
                    "workProductDeclarations": [
                        {"path": "reports/result.md", "isPrimary": True},
                        {"path": "reports/notes.md", "isPrimary": False},
                    ],
                },
                actor_type="agent",
                actor_id=agent.id,
                run_id=run.id,
            )

            assert updated is not None
            assert updated["status"] == "in_progress"
            repeated = await IssueService(session).update_issue(
                issue.id,
                {"status": "done", "comment": "Report completed."},
                actor_type="agent",
                actor_id=agent.id,
                run_id=run.id,
            )
            assert repeated is not None
            assert repeated["status"] == "in_progress"
            governance = IssueCompletionGovernance(session)
            session.add(
                IssueWorkProduct(
                    org_id=org.id,
                    issue_id=issue.id,
                    type="document",
                    provider="octopus",
                    external_id=f"fabricated:{run.id}",
                    title="reports/result.md",
                    status="active",
                    is_primary=True,
                    created_by_run_id=run.id,
                )
            )
            await session.flush()
            missing = await governance.validate(run, issue)
            assert missing.applicable is True
            assert missing.completed is False
            assert "reports/result.md" in (missing.error or "")

            reports = workspace / "reports"
            reports.mkdir()
            reports.joinpath("result.md").write_text("result", encoding="utf-8")
            reports.joinpath("notes.md").write_text("notes", encoding="utf-8")
            session.add_all(
                [
                    IssueWorkProduct(
                        org_id=org.id,
                        issue_id=issue.id,
                        type="document",
                        provider="octopus",
                        external_id=f"workspace:{run.id}:reports/result.md",
                        title="reports/result.md",
                        status="active",
                        is_primary=True,
                        metadata_json={
                            "source": "shared_workspace_scan",
                            "workspacePath": "reports/result.md",
                        },
                        created_by_run_id=run.id,
                    ),
                    IssueWorkProduct(
                        org_id=org.id,
                        issue_id=issue.id,
                        type="document",
                        provider="octopus",
                        external_id=f"workspace:{run.id}:reports/notes.md",
                        title="reports/notes.md",
                        status="active",
                        is_primary=False,
                        metadata_json={
                            "source": "shared_workspace_scan",
                            "workspacePath": "reports/notes.md",
                        },
                        created_by_run_id=run.id,
                    ),
                ]
            )
            await session.flush()
            completed = await governance.validate(run, issue, apply=True)
            await session.refresh(issue)

            assert completed.applicable is True
            assert completed.completed is True
            assert issue.status == "done"
            reasons = (
                (
                    await session.execute(
                        select(ActivityLog.details).where(
                            ActivityLog.run_id == run.id,
                            ActivityLog.entity_id == issue.id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert any(
                isinstance(details, dict)
                and details.get("reason") == "declared_outputs_validated"
                for details in reasons
            )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("invalid_binding", ["stale", "other_issue", "other_lock"])
async def test_completion_request_requires_the_active_issue_run(
    invalid_binding: str,
) -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Run binding", url_key=f"binding-{invalid_binding}")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Writer")
            session.add(agent)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                title="Bound issue",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            other = Issue(org_id=org.id, title="Other issue")
            session.add_all([issue, other])
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="failed" if invalid_binding == "stale" else "running",
                context_snapshot={
                    "issueId": other.id
                    if invalid_binding == "other_issue"
                    else issue.id
                },
            )
            session.add(run)
            await session.flush()
            issue.execution_run_id = (
                "another-run" if invalid_binding == "other_lock" else run.id
            )
            issue.checkout_run_id = run.id
            await session.flush()

            with pytest.raises(ValueError, match="active Agent Run"):
                await IssueService(session).update_issue(
                    issue.id,
                    {
                        "status": "done",
                        "comment": "Done.",
                        "workProductDeclarations": [
                            {"path": "reports/result.md", "isPrimary": True}
                        ],
                    },
                    actor_type="agent",
                    actor_id=agent.id,
                    run_id=run.id,
                )
    finally:
        await engine.dispose()


async def test_declared_completion_cannot_bypass_open_child() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Open child", url_key="open-child")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent writer")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            session.add(
                Issue(
                    org_id=org.id,
                    parent_id=parent.id,
                    title="Open child",
                    status="in_progress",
                )
            )
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={"issueId": parent.id},
            )
            session.add(run)
            await session.flush()
            parent.execution_run_id = run.id
            parent.checkout_run_id = run.id
            await session.flush()

            with pytest.raises(ValueError, match="still open"):
                await IssueService(session).update_issue(
                    parent.id,
                    {
                        "status": "done",
                        "comment": "Done.",
                        "workProductDeclarations": [
                            {"path": "reports/final.md", "isPrimary": True}
                        ],
                    },
                    actor_type="agent",
                    actor_id=agent.id,
                    run_id=run.id,
                )
    finally:
        await engine.dispose()


async def test_no_output_completion_preserves_existing_issue_semantics() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="No output", url_key="no-output")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Worker")
            session.add(agent)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                title="No file work",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            session.add(issue)
            await session.flush()
            terminal_run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": issue.id},
            )
            session.add(terminal_run)
            await session.flush()

            updated = await IssueService(session).update_issue(
                issue.id,
                {"status": "done", "comment": "No file was required."},
                actor_type="agent",
                actor_id=agent.id,
                run_id=terminal_run.id,
            )

            assert updated is not None
            assert updated["status"] == "done"
    finally:
        await engine.dispose()


async def test_closed_ancestor_rejects_reopen_review_and_reparent() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Closed ancestor", url_key="closed-ancestor")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Worker")
            reviewer = Agent(org_id=org.id, name="Reviewer")
            session.add_all([agent, reviewer])
            await session.flush()
            parent = Issue(org_id=org.id, title="Closed parent", status="done")
            session.add(parent)
            await session.flush()
            done_child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Done child",
                status="done",
            )
            review_child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Review child",
                status="blocked",
                assignee_agent_id=agent.id,
                reviewer_agent_id=reviewer.id,
            )
            active_target = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Active target",
                status="todo",
            )
            root_issue = Issue(org_id=org.id, title="Root issue", status="todo")
            session.add_all([done_child, review_child, active_target, root_issue])
            await session.flush()

            with pytest.raises(ValueError, match="Reopen ancestor"):
                await IssueService(session).update_issue(
                    done_child.id,
                    {"reopen": True},
                    actor_type="user",
                    actor_id="operator",
                )
            with pytest.raises(ValueError, match="Reopen ancestor"):
                await IssueService(session).update_issue(
                    review_child.id,
                    {"reviewDecision": {"decision": "request_changes"}},
                    actor_type="agent",
                    actor_id=reviewer.id,
                )
            with pytest.raises(ValueError, match="Reopen ancestor"):
                await IssueService(session).update_issue(
                    root_issue.id,
                    {"parentId": active_target.id},
                    actor_type="user",
                    actor_id="operator",
                )
    finally:
        await engine.dispose()


async def test_completion_rechecks_children_added_after_request(
    tmp_path: Path,
) -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Late child", url_key="late-child")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent worker")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            workspace = tmp_path / "late-child"
            reports = workspace / "reports"
            reports.mkdir(parents=True)
            reports.joinpath("result.md").write_text("result", encoding="utf-8")
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={
                    "issueId": parent.id,
                    "workspace": {"octopusWorkspace": {"cwd": str(workspace)}},
                },
            )
            session.add(run)
            await session.flush()
            parent.execution_run_id = run.id
            parent.checkout_run_id = run.id
            await session.flush()
            await IssueService(session).update_issue(
                parent.id,
                {
                    "status": "done",
                    "workProductDeclarations": [
                        {"path": "reports/result.md", "isPrimary": True}
                    ],
                },
                actor_type="agent",
                actor_id=agent.id,
                run_id=run.id,
            )
            session.add_all(
                [
                    Issue(
                        org_id=org.id,
                        parent_id=parent.id,
                        title="Late child",
                        status="in_progress",
                    ),
                    IssueWorkProduct(
                        org_id=org.id,
                        issue_id=parent.id,
                        type="document",
                        provider="octopus",
                        title="reports/result.md",
                        status="active",
                        is_primary=True,
                        metadata_json={
                            "source": "shared_workspace_scan",
                            "workspacePath": "reports/result.md",
                        },
                        created_by_run_id=run.id,
                    ),
                ]
            )
            await session.flush()

            result = await IssueCompletionGovernance(session).validate(
                run, parent, apply=True
            )
            await session.refresh(parent)

            assert result.applicable is True
            assert result.completed is False
            assert "remain unsettled" in (result.error or "")
            assert parent.status == "in_progress"
    finally:
        await engine.dispose()


async def test_accepted_incomplete_child_does_not_block_declared_completion(
    tmp_path: Path,
) -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Accepted child", url_key="accepted-child")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent worker")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Accepted blocked child",
                status="blocked",
            )
            session.add(child)
            workspace = tmp_path / "accepted-child"
            reports = workspace / "reports"
            reports.mkdir(parents=True)
            reports.joinpath("result.md").write_text("result", encoding="utf-8")
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={
                    "issueId": parent.id,
                    "workspace": {"octopusWorkspace": {"cwd": str(workspace)}},
                },
            )
            session.add(run)
            await session.flush()
            parent.execution_run_id = run.id
            parent.checkout_run_id = run.id
            session.add(
                ActivityLog(
                    org_id=org.id,
                    actor_type="user",
                    actor_id="operator",
                    action="issue.incomplete_accepted",
                    entity_type="issue",
                    entity_id=parent.id,
                    details={"childIssueIds": [child.id], "reason": "accepted"},
                )
            )
            await session.flush()

            requested = await IssueService(session).update_issue(
                parent.id,
                {
                    "status": "done",
                    "workProductDeclarations": [
                        {"path": "reports/result.md", "isPrimary": True}
                    ],
                },
                actor_type="agent",
                actor_id=agent.id,
                run_id=run.id,
            )
            assert requested is not None
            assert requested["status"] == "in_progress"
            session.add(
                IssueWorkProduct(
                    org_id=org.id,
                    issue_id=parent.id,
                    type="document",
                    provider="octopus",
                    title="reports/result.md",
                    status="active",
                    is_primary=True,
                    metadata_json={
                        "source": "shared_workspace_scan",
                        "workspacePath": "reports/result.md",
                    },
                    created_by_run_id=run.id,
                )
            )
            await session.flush()

            result = await IssueCompletionGovernance(session).validate(
                run, parent, apply=True
            )
            await session.refresh(parent)

            assert result.completed is True
            assert parent.status == "done"
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.getenv("OCTOPUS_TEST_POSTGRES_URL"),
    reason="requires OCTOPUS_TEST_POSTGRES_URL",
)
async def test_postgres_child_insert_and_parent_completion_share_root_lock(
    tmp_path: Path,
) -> None:
    database_url = os.environ["OCTOPUS_TEST_POSTGRES_URL"]
    engine = create_database_engine(database_url)
    factory: async_sessionmaker = create_session_factory(engine)
    schema_name = f"octopus_completion_lock_{uuid.uuid4().hex}"
    quoted_schema = f'"{schema_name}"'
    child_session = None
    completion_session = None
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            await connection.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
            await connection.run_sync(Base.metadata.create_all)

        workspace = tmp_path / "postgres-lock"
        reports = workspace / "reports"
        reports.mkdir(parents=True)
        reports.joinpath("result.md").write_text("result", encoding="utf-8")
        async with factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
                org = Organization(
                    name="Completion lock",
                    url_key=f"completion-lock-{uuid.uuid4().hex}",
                    issue_prefix="CLK",
                )
                session.add(org)
                await session.flush()
                agent = Agent(org_id=org.id, name="Parent worker")
                session.add(agent)
                await session.flush()
                parent = Issue(
                    org_id=org.id,
                    title="Parent",
                    status="in_progress",
                    assignee_agent_id=agent.id,
                )
                session.add(parent)
                await session.flush()
                run = HeartbeatRun(
                    org_id=org.id,
                    agent_id=agent.id,
                    invocation_source="assignment",
                    trigger_detail="system",
                    status="running",
                    context_snapshot={
                        "issueId": parent.id,
                        "workspace": {"octopusWorkspace": {"cwd": str(workspace)}},
                    },
                )
                session.add(run)
                await session.flush()
                parent.execution_run_id = run.id
                parent.checkout_run_id = run.id
                session.add_all(
                    [
                        IssueWorkProduct(
                            org_id=org.id,
                            issue_id=parent.id,
                            type="document",
                            provider="octopus",
                            title="reports/result.md",
                            status="active",
                            is_primary=True,
                            metadata_json={
                                "source": "shared_workspace_scan",
                                "workspacePath": "reports/result.md",
                            },
                            created_by_run_id=run.id,
                        ),
                        ActivityLog(
                            org_id=org.id,
                            actor_type="agent",
                            actor_id=agent.id,
                            action="issue.completion_requested",
                            entity_type="issue",
                            entity_id=parent.id,
                            agent_id=agent.id,
                            run_id=run.id,
                            details={
                                "version": 1,
                                "runId": run.id,
                                "declaredWorkProducts": [
                                    {
                                        "path": "reports/result.md",
                                        "isPrimary": True,
                                    }
                                ],
                            },
                        ),
                    ]
                )
                org_id = org.id
                parent_id = parent.id
                run_id = run.id

        child_session = factory()
        completion_session = factory()
        await child_session.begin()
        await completion_session.begin()
        await child_session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
        await completion_session.execute(
            text(f"SET LOCAL search_path TO {quoted_schema}")
        )
        await IssueService(child_session).create_issue(
            org_id,
            {"title": "Concurrent child", "parentId": parent_id},
            actor_type="user",
            actor_id="operator",
        )

        run = await completion_session.get(HeartbeatRun, run_id)
        parent = await completion_session.get(Issue, parent_id)
        assert run is not None and parent is not None
        completion_task = asyncio.create_task(
            IssueCompletionGovernance(completion_session).validate(
                run, parent, apply=True
            )
        )
        await asyncio.sleep(0.05)
        assert not completion_task.done()
        await child_session.commit()

        result = await asyncio.wait_for(completion_task, timeout=5)
        assert result.completed is False
        assert "remain unsettled" in (result.error or "")
        await completion_session.commit()

        async with factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
                persisted = await session.get(Issue, parent_id)
                assert persisted is not None
                assert persisted.status == "in_progress"
    finally:
        if child_session is not None:
            await child_session.close()
        if completion_session is not None:
            await completion_session.close()
        async with engine.begin() as connection:
            await connection.execute(
                text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE")
            )
        await engine.dispose()


async def test_missing_declared_output_blocks_issue_after_failed_finalization() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Missing output", url_key="missing-output")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Writer")
            session.add(agent)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                title="Create report",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={"issueId": issue.id},
            )
            session.add(run)
            await session.flush()
            issue.execution_run_id = run.id
            issue.checkout_run_id = run.id
            await session.flush()
            await IssueService(session).update_issue(
                issue.id,
                {
                    "status": "done",
                    "comment": "Done.",
                    "workProductDeclarations": [
                        {"path": "reports/missing.md", "isPrimary": True}
                    ],
                },
                actor_type="agent",
                actor_id=agent.id,
                run_id=run.id,
            )
            run.status = "failed"
            run.error = "Issue completion output validation failed"
            run.error_code = "closeout_missing"
            await session.flush()

            blocked = await IssueCompletionGovernance(session).block_failed_request(
                run, issue
            )
            await session.refresh(issue)

            assert blocked is True
            assert issue.status == "blocked"
    finally:
        await engine.dispose()


async def test_retry_restores_issue_blocked_by_missing_declared_output() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Retry output", url_key="retry-output")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Writer")
            session.add(agent)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                title="Create report",
                status="blocked",
                assignee_agent_id=agent.id,
            )
            session.add(issue)
            await session.flush()
            failed = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="failed",
                error="Declared output missing",
                error_code="closeout_missing",
                context_snapshot={"issueId": issue.id},
            )
            running = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={"issueId": issue.id},
            )
            session.add_all([failed, running])
            await session.flush()
            issue.execution_run_id = running.id
            issue.checkout_run_id = running.id
            session.add(
                ActivityLog(
                    org_id=org.id,
                    actor_type="system",
                    actor_id="run_finalization_service",
                    action="issue.updated",
                    entity_type="issue",
                    entity_id=issue.id,
                    agent_id=agent.id,
                    run_id=failed.id,
                    details={
                        "status": "blocked",
                        "fromStatus": "in_progress",
                        "reason": "declared_outputs_missing",
                        "runId": failed.id,
                    },
                )
            )
            await session.flush()

            restored = await HeartbeatService(
                session
            )._restore_system_blocked_issue_for_execution(running)
            await session.refresh(issue)

            assert restored is True
            assert issue.status == "in_progress"
    finally:
        await engine.dispose()


async def test_system_retry_cannot_reactivate_child_below_done_parent() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Closed retry", url_key="closed-retry")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Worker")
            session.add(agent)
            await session.flush()
            parent = Issue(org_id=org.id, title="Done parent", status="done")
            session.add(parent)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Blocked child",
                status="blocked",
                assignee_agent_id=agent.id,
            )
            session.add(issue)
            await session.flush()
            failed = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="failed",
                error_code="closeout_missing",
                context_snapshot={"issueId": issue.id},
            )
            running = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={"issueId": issue.id},
            )
            session.add_all([failed, running])
            await session.flush()
            issue.execution_run_id = running.id
            issue.checkout_run_id = running.id
            session.add(
                ActivityLog(
                    org_id=org.id,
                    actor_type="system",
                    actor_id="run_finalization_service",
                    action="issue.updated",
                    entity_type="issue",
                    entity_id=issue.id,
                    agent_id=agent.id,
                    run_id=failed.id,
                    details={
                        "status": "blocked",
                        "fromStatus": "in_progress",
                        "reason": "declared_outputs_missing",
                        "runId": failed.id,
                    },
                )
            )
            await session.flush()

            with pytest.raises(ValueError, match="Reopen ancestor"):
                await HeartbeatService(
                    session
                )._restore_system_blocked_issue_for_execution(running)
            await session.refresh(issue)

            assert issue.status == "blocked"
    finally:
        await engine.dispose()


async def test_stale_completion_effect_does_not_overwrite_cancelled_issue(
    tmp_path: Path,
) -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Stale output", url_key="stale-output")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Writer")
            session.add(agent)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                title="Create report",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            session.add(issue)
            await session.flush()
            workspace = tmp_path / "stale-workspace"
            reports = workspace / "reports"
            reports.mkdir(parents=True)
            reports.joinpath("result.md").write_text("result", encoding="utf-8")
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={
                    "issueId": issue.id,
                    "workspace": {"octopusWorkspace": {"cwd": str(workspace)}},
                },
            )
            session.add(run)
            await session.flush()
            issue.execution_run_id = run.id
            issue.checkout_run_id = run.id
            await session.flush()
            await IssueService(session).update_issue(
                issue.id,
                {
                    "status": "done",
                    "comment": "Done.",
                    "workProductDeclarations": [
                        {"path": "reports/result.md", "isPrimary": True}
                    ],
                },
                actor_type="agent",
                actor_id=agent.id,
                run_id=run.id,
            )
            session.add(
                IssueWorkProduct(
                    org_id=org.id,
                    issue_id=issue.id,
                    type="document",
                    provider="octopus",
                    title="reports/result.md",
                    status="active",
                    is_primary=True,
                    metadata_json={
                        "source": "shared_workspace_scan",
                        "workspacePath": "reports/result.md",
                    },
                    created_by_run_id=run.id,
                )
            )
            issue.status = "cancelled"
            issue.execution_run_id = None
            issue.checkout_run_id = None
            await session.flush()

            result = await IssueCompletionGovernance(session).validate(
                run, issue, apply=True
            )
            await session.refresh(issue)

            assert result.applicable is True
            assert result.completed is False
            assert issue.status == "cancelled"
    finally:
        await engine.dispose()
