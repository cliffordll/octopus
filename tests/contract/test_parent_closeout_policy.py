from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import (
    ActivityLog,
    Agent,
    AgentWakeupRequest,
    Base,
    HeartbeatRun,
    Issue,
    IssueWorkProduct,
    Organization,
)
from packages.shared.validators.issue import validate_create_child_issues
from server.services.heartbeat import HeartbeatService
from server.services.issues import IssueService
from server.services.parent_closeout_governance import ParentCloseoutGovernance


async def test_parent_output_request_is_validated_before_issue_completion() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Closeout", url_key="closeout", issue_prefix="CLO")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
            reviewer = Agent(org_id=org.id, name="Reviewer Agent")
            session.add_all([agent, reviewer])
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=agent.id,
                reviewer_agent_id=reviewer.id,
            )
            session.add(parent)
            await session.flush()
            origin_run_id = str(uuid.uuid4())
            policy = {
                "version": 1,
                "mode": "parent_output_required",
                "requirements": {
                    "minimumOutputs": 1,
                    "primaryOutputRequired": True,
                },
            }
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Research",
                status="done",
                origin_kind="delegation",
                origin_run_id=origin_run_id,
                closeout_policy=policy,
                completed_at=datetime.now(UTC),
            )
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={
                    "issueId": parent.id,
                    "wakeReason": "issue_children_settled",
                },
            )
            session.add_all([child, run])
            await session.flush()
            parent.execution_run_id = run.id
            parent.checkout_run_id = run.id
            await session.flush()

            with pytest.raises(ValueError, match="cannot bypass"):
                await IssueService(session).update_issue(
                    parent.id,
                    {"status": "done"},
                    actor_type="board",
                    actor_id="local-board",
                )

            with pytest.raises(ValueError, match="--primary-work-product <path>"):
                await IssueService(session).update_issue(
                    parent.id,
                    {"status": "done", "comment": "Final report completed."},
                    actor_type="agent",
                    actor_id=agent.id,
                    run_id=run.id,
                )
            missing_declaration_request = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.action == "issue.closeout_requested",
                        ActivityLog.run_id == run.id,
                    )
                )
            ).scalar_one_or_none()
            assert missing_declaration_request is None

            updated = await IssueService(session).update_issue(
                parent.id,
                {
                    "status": "done",
                    "comment": "Final report completed.",
                    "workProductDeclarations": [
                        {"path": "reports/final.md", "isPrimary": True}
                    ],
                },
                actor_type="agent",
                actor_id=agent.id,
                run_id=run.id,
            )

            assert updated is not None
            assert updated["status"] == "in_progress"
            request = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.action == "issue.closeout_requested",
                        ActivityLog.run_id == run.id,
                    )
                )
            ).scalar_one()
            assert request.details["delegationOriginRunId"] == origin_run_id
            assert request.details["declaredWorkProducts"] == [
                {"path": "reports/final.md", "isPrimary": True}
            ]
            await session.refresh(run)
            run_context = run.context_snapshot
            assert isinstance(run_context, dict)
            assert run_context["delegationOriginRunId"] == origin_run_id
            assert run_context["closeoutPolicy"] == policy

            session.add(
                IssueWorkProduct(
                    org_id=org.id,
                    issue_id=parent.id,
                    type="document",
                    provider="octopus",
                    title="reports/final.md",
                    status="active",
                    is_primary=True,
                    created_by_run_id=run.id,
                )
            )
            await session.flush()
            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)
            replayed = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)
            await session.refresh(parent)
            finalization_activities = (
                (
                    await session.execute(
                        select(ActivityLog).where(
                            ActivityLog.run_id == run.id,
                            ActivityLog.action == "issue.updated",
                        )
                    )
                )
                .scalars()
                .all()
            )
            reviewer_wakeup = (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == reviewer.id,
                        AgentWakeupRequest.reason == "issue_review_requested",
                    )
                )
            ).scalar_one()

            assert final.status == "succeeded"
            assert replayed.status == "succeeded"
            assert parent.status == "in_review"
            assert len(finalization_activities) == 1
            assert reviewer_wakeup.status == "queued"
    finally:
        await engine.dispose()


async def test_stale_parent_closeout_cannot_overwrite_cancelled_issue() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Stale closeout", url_key="stale-closeout")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
            session.add(agent)
            await session.flush()
            origin_run_id = str(uuid.uuid4())
            policy = {
                "version": 1,
                "mode": "parent_output_required",
                "requirements": {
                    "minimumOutputs": 1,
                    "primaryOutputRequired": True,
                },
            }
            parent = Issue(
                org_id=org.id,
                title="Cancelled parent",
                status="cancelled",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="continuation",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={
                    "issueId": parent.id,
                    "wakeReason": "issue_children_settled",
                    "delegationOriginRunId": origin_run_id,
                    "closeoutPolicy": policy,
                },
            )
            session.add(run)
            await session.flush()
            session.add_all(
                [
                    Issue(
                        org_id=org.id,
                        parent_id=parent.id,
                        title="Done child",
                        status="done",
                        origin_kind="delegation",
                        origin_run_id=origin_run_id,
                        closeout_policy=policy,
                    ),
                    IssueWorkProduct(
                        org_id=org.id,
                        issue_id=parent.id,
                        type="document",
                        provider="octopus",
                        title="reports/final.md",
                        status="active",
                        is_primary=True,
                        created_by_run_id=run.id,
                    ),
                    ActivityLog(
                        org_id=org.id,
                        actor_type="agent",
                        actor_id=agent.id,
                        action="issue.closeout_requested",
                        entity_type="issue",
                        entity_id=parent.id,
                        agent_id=agent.id,
                        run_id=run.id,
                        details={
                            "version": 1,
                            "runId": run.id,
                            "delegationOriginRunId": origin_run_id,
                            "declaredWorkProducts": [
                                {
                                    "path": "reports/final.md",
                                    "isPrimary": True,
                                }
                            ],
                        },
                    ),
                ]
            )
            await session.flush()

            result = await ParentCloseoutGovernance(
                session
            ).finalize_parent_output_request(run, parent)
            await session.refresh(parent)

            assert result.applicable is True
            assert result.completed is False
            assert "superseded" in (result.error or "")
            assert parent.status == "cancelled"
            skipped = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.run_id == run.id,
                        ActivityLog.action == "issue.closeout_effect_skipped",
                    )
                )
            ).scalar_one()
            assert skipped.details["reason"] == "stale_issue_execution"
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.getenv("OCTOPUS_TEST_POSTGRES_URL"),
    reason="requires OCTOPUS_TEST_POSTGRES_URL",
)
async def test_postgres_parent_closeout_and_nested_child_insert_share_lock() -> None:
    database_url = os.environ["OCTOPUS_TEST_POSTGRES_URL"]
    engine = create_database_engine(database_url)
    factory: async_sessionmaker = create_session_factory(engine)
    schema_name = f"octopus_parent_closeout_lock_{uuid.uuid4().hex}"
    quoted_schema = f'"{schema_name}"'
    child_session = None
    closeout_session = None
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            await connection.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
            await connection.run_sync(Base.metadata.create_all)

        async with factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
                org = Organization(
                    name="Parent closeout lock",
                    url_key=f"parent-closeout-lock-{uuid.uuid4().hex}",
                    issue_prefix="PCL",
                )
                session.add(org)
                await session.flush()
                agent = Agent(org_id=org.id, name="Parent Agent")
                session.add(agent)
                await session.flush()
                origin_run_id = str(uuid.uuid4())
                policy = {
                    "version": 1,
                    "mode": "parent_output_required",
                    "requirements": {
                        "minimumOutputs": 1,
                        "primaryOutputRequired": True,
                    },
                }
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
                    invocation_source="continuation",
                    trigger_detail="system",
                    status="succeeded",
                    context_snapshot={
                        "issueId": parent.id,
                        "wakeReason": "issue_children_settled",
                        "delegationOriginRunId": origin_run_id,
                        "closeoutPolicy": policy,
                    },
                )
                session.add(run)
                await session.flush()
                parent.execution_run_id = run.id
                parent.checkout_run_id = run.id
                delegated_child = Issue(
                    org_id=org.id,
                    parent_id=parent.id,
                    title="Settled delegated child",
                    status="done",
                    origin_kind="delegation",
                    origin_run_id=origin_run_id,
                    closeout_policy=policy,
                )
                session.add_all(
                    [
                        delegated_child,
                        IssueWorkProduct(
                            org_id=org.id,
                            issue_id=parent.id,
                            type="document",
                            provider="octopus",
                            title="reports/final.md",
                            status="active",
                            is_primary=True,
                            created_by_run_id=run.id,
                        ),
                        ActivityLog(
                            org_id=org.id,
                            actor_type="agent",
                            actor_id=agent.id,
                            action="issue.closeout_requested",
                            entity_type="issue",
                            entity_id=parent.id,
                            agent_id=agent.id,
                            run_id=run.id,
                            details={
                                "version": 1,
                                "runId": run.id,
                                "delegationOriginRunId": origin_run_id,
                                "declaredWorkProducts": [
                                    {
                                        "path": "reports/final.md",
                                        "isPrimary": True,
                                    }
                                ],
                            },
                        ),
                    ]
                )
                await session.flush()
                org_id = org.id
                parent_id = parent.id
                run_id = run.id
                delegated_child_id = delegated_child.id

        child_session = factory()
        closeout_session = factory()
        await child_session.begin()
        await closeout_session.begin()
        await child_session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
        await closeout_session.execute(
            text(f"SET LOCAL search_path TO {quoted_schema}")
        )
        reopened = await IssueService(child_session).update_issue(
            delegated_child_id,
            {"reopen": True},
            actor_type="user",
            actor_id="operator",
        )
        assert reopened is not None
        assert reopened["status"] == "todo"
        await IssueService(child_session).create_issue(
            org_id,
            {"title": "Concurrent grandchild", "parentId": delegated_child_id},
            actor_type="user",
            actor_id="operator",
        )

        run = await closeout_session.get(HeartbeatRun, run_id)
        parent = await closeout_session.get(Issue, parent_id)
        assert run is not None and parent is not None
        closeout_task = asyncio.create_task(
            ParentCloseoutGovernance(closeout_session).finalize_parent_output_request(
                run, parent
            )
        )
        await asyncio.sleep(0.05)
        assert not closeout_task.done()
        await child_session.commit()

        result = await asyncio.wait_for(closeout_task, timeout=5)
        assert result.completed is False
        assert "remain unsettled" in (result.error or "")
        await closeout_session.commit()

        async with factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
                persisted = await session.get(Issue, parent_id)
                assert persisted is not None
                assert persisted.status == "in_progress"
    finally:
        if child_session is not None:
            await child_session.close()
        if closeout_session is not None:
            await closeout_session.close()
        async with engine.begin() as connection:
            await connection.execute(
                text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE")
            )
        await engine.dispose()


def test_parent_output_policy_requires_a_real_primary_output() -> None:
    with pytest.raises(ValueError, match="at least one primary output"):
        validate_create_child_issues(
            {
                "closeoutPolicy": {
                    "version": 1,
                    "mode": "parent_output_required",
                    "requirements": {
                        "minimumOutputs": 0,
                        "primaryOutputRequired": True,
                    },
                },
                "children": [{"title": "Child"}],
            }
        )


@pytest.mark.parametrize(
    ("wake_reason", "child_status"),
    [
        ("issue_assigned", "todo"),
        ("issue_comment_mentioned", "done"),
    ],
)
async def test_parent_progress_run_does_not_require_closeout(
    wake_reason: str, child_status: str
) -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Progress", url_key="progress", issue_prefix="PRO")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
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
            origin_run_id = str(uuid.uuid4())
            policy = {
                "version": 1,
                "mode": "parent_output_required",
                "requirements": {
                    "minimumOutputs": 1,
                    "primaryOutputRequired": True,
                },
            }
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Research",
                status=child_status,
                origin_kind="delegation",
                origin_run_id=origin_run_id,
                closeout_policy=policy,
                completed_at=(datetime.now(UTC) if child_status == "done" else None),
            )
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={
                    "issueId": parent.id,
                    "wakeReason": wake_reason,
                    "delegationOriginRunId": origin_run_id,
                    "closeoutPolicy": policy,
                },
            )
            session.add_all([child, run])
            await session.flush()

            result = await ParentCloseoutGovernance(
                session
            ).finalize_parent_output_request(run, parent, apply=False)

            assert result.applicable is False
            assert result.completed is False
            assert result.error is None
    finally:
        await engine.dispose()


async def test_settlement_continuation_requires_parent_closeout_request() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                name="Settlement", url_key="settlement", issue_prefix="SET"
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
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
            origin_run_id = str(uuid.uuid4())
            policy = {
                "version": 1,
                "mode": "parent_output_required",
                "requirements": {
                    "minimumOutputs": 1,
                    "primaryOutputRequired": True,
                },
            }
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Research",
                status="done",
                origin_kind="delegation",
                origin_run_id=origin_run_id,
                closeout_policy=policy,
                completed_at=datetime.now(UTC),
            )
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="continuation",
                trigger_detail="system",
                status="running",
                context_snapshot={
                    "issueId": parent.id,
                    "wakeReason": "issue_children_settled",
                    "delegationOriginRunId": origin_run_id,
                    "closeoutPolicy": policy,
                },
            )
            session.add_all([child, run])
            await session.flush()

            result = await ParentCloseoutGovernance(
                session
            ).finalize_parent_output_request(run, parent, apply=False)

            assert result.applicable is True
            assert result.completed is False
            assert result.error is not None
            assert "Parent closeout request is missing" in result.error
    finally:
        await engine.dispose()


async def test_recovery_preserves_terminal_run_when_parent_request_is_missing() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Missing", url_key="missing", issue_prefix="MIS")
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
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
            origin_run_id = str(uuid.uuid4())
            policy = {
                "version": 1,
                "mode": "parent_output_required",
                "requirements": {
                    "minimumOutputs": 1,
                    "primaryOutputRequired": True,
                },
            }
            session.add(
                Issue(
                    org_id=org.id,
                    parent_id=parent.id,
                    title="Research",
                    status="done",
                    origin_kind="delegation",
                    origin_run_id=origin_run_id,
                    closeout_policy=policy,
                    completed_at=datetime.now(UTC),
                )
            )
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={
                    "issueId": parent.id,
                    "wakeReason": "issue_children_settled",
                    "delegationOriginRunId": origin_run_id,
                    "closeoutPolicy": policy,
                },
            )
            session.add(run)
            await session.flush()

            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)
            await session.refresh(parent)

            assert final.status == "succeeded"
            assert final.error_code is None
            assert parent.status == "in_progress"
    finally:
        await engine.dispose()


async def test_child_outputs_policy_always_queues_parent_continuation() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                name="Automatic", url_key="automatic", issue_prefix="AUT"
            )
            session.add(org)
            await session.flush()
            parent_agent = Agent(org_id=org.id, name="Parent Agent")
            child_agent = Agent(org_id=org.id, name="Child Agent")
            session.add_all([parent_agent, child_agent])
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=parent_agent.id,
            )
            session.add(parent)
            await session.flush()
            origin_run_id = str(uuid.uuid4())
            policy = {"version": 1, "mode": "child_outputs_are_final"}
            children = [
                Issue(
                    org_id=org.id,
                    parent_id=parent.id,
                    title=title,
                    status="done",
                    assignee_agent_id=child_agent.id,
                    origin_kind="delegation",
                    origin_run_id=origin_run_id,
                    closeout_policy=policy,
                    completed_at=datetime.now(UTC),
                )
                for title in ("A", "B")
            ]
            session.add_all(children)
            await session.flush()
            child_run = HeartbeatRun(
                org_id=org.id,
                agent_id=child_agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": children[-1].id},
            )
            session.add(child_run)
            await session.flush()

            await HeartbeatService(session)._wake_parent_after_child_settled(
                child_run, children[-1]
            )
            await HeartbeatService(session)._wake_parent_after_child_settled(
                child_run, children[-1]
            )
            await session.refresh(parent)
            parent_runs = (
                (
                    await session.execute(
                        select(HeartbeatRun).where(
                            HeartbeatRun.agent_id == parent_agent.id
                        )
                    )
                )
                .scalars()
                .all()
            )

            assert parent.status == "in_progress"
            assert len(parent_runs) == 1
            continuation = parent_runs[0]
            assert continuation.status == "queued"
            assert continuation.agent_id == parent_agent.id
            assert continuation.context_snapshot["wakeReason"] == (
                "issue_children_settled"
            )
            assert continuation.context_snapshot["closeoutPolicy"] == policy
    finally:
        await engine.dispose()
