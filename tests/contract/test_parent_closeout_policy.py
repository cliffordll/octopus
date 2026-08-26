from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy import select
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
from server.services.delegation_closeout import DelegationBatchStore
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

            with pytest.raises(ValueError, match="cannot bypass"):
                await IssueService(session).update_issue(
                    parent.id,
                    {"status": "done"},
                    actor_type="board",
                    actor_id="local-board",
                )

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


async def test_child_outputs_policy_completes_parent_without_parent_run() -> None:
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
                assignee_agent_id=None,
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
            for child in children[:1]:
                session.add(
                    IssueWorkProduct(
                        org_id=org.id,
                        issue_id=child.id,
                        type="document",
                        provider="octopus",
                        title=f"reports/{child.id}.md",
                        status="active",
                        is_primary=True,
                    )
                )
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
            await session.refresh(parent)
            assert parent.status == "blocked"

            session.add(
                IssueWorkProduct(
                    org_id=org.id,
                    issue_id=children[-1].id,
                    type="document",
                    provider="octopus",
                    title=f"reports/{children[-1].id}.md",
                    status="active",
                    is_primary=True,
                )
            )
            parent.status = "in_progress"
            await session.flush()
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

            assert parent.status == "done"
            assert parent_runs == []
            actions = (
                (
                    await session.execute(
                        select(ActivityLog.action).where(
                            ActivityLog.entity_id == parent.id,
                            ActivityLog.action.in_(
                                (
                                    "issue.child_outputs_closeout_failed",
                                    "issue.child_outputs_closeout_completed",
                                )
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert actions.count("issue.child_outputs_closeout_failed") == 1
            assert actions.count("issue.child_outputs_closeout_completed") == 1
    finally:
        await engine.dispose()


async def test_incomplete_acceptance_does_not_leak_into_a_later_batch() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(name="Scoped", url_key="scoped", issue_prefix="SCO")
            session.add(org)
            await session.flush()
            parent = Issue(org_id=org.id, title="Parent", status="in_progress")
            session.add(parent)
            await session.flush()
            policy = {"version": 1, "mode": "child_outputs_are_final"}
            old_origin = str(uuid.uuid4())
            new_origin = str(uuid.uuid4())
            old_child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Old",
                status="blocked",
                origin_kind="delegation",
                origin_run_id=old_origin,
                closeout_policy=policy,
            )
            new_child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="New",
                status="blocked",
                origin_kind="delegation",
                origin_run_id=new_origin,
                closeout_policy=policy,
            )
            session.add_all([old_child, new_child])
            await session.flush()
            session.add(
                ActivityLog(
                    org_id=org.id,
                    actor_type="board",
                    actor_id="local-board",
                    action="issue.incomplete_accepted",
                    entity_type="issue",
                    entity_id=parent.id,
                    details={
                        "childIssueIds": [old_child.id],
                        "delegationOriginRunId": old_origin,
                        "reason": "Old batch only",
                    },
                )
            )
            await session.flush()
            batch = await DelegationBatchStore(session).for_parent(
                parent.id, org_id=org.id, origin_run_id=new_origin
            )
            assert batch is not None

            result = await ParentCloseoutGovernance(session).complete_child_outputs(
                parent,
                batch,
                child_run_id=None,
                child_agent_id=None,
            )
            await session.refresh(parent)

            assert result.completed is False
            assert parent.status == "blocked"
            assert "blocked or cancelled" in (result.error or "")

            session.add(
                ActivityLog(
                    org_id=org.id,
                    actor_type="board",
                    actor_id="local-board",
                    action="issue.incomplete_accepted",
                    entity_type="issue",
                    entity_id=parent.id,
                    details={
                        "childIssueIds": [new_child.id],
                        "delegationOriginRunId": new_origin,
                        "reason": "Accept this batch",
                    },
                )
            )
            parent.status = "in_progress"
            await session.flush()
            recovered = await ParentCloseoutGovernance(session).complete_child_outputs(
                parent,
                batch,
                child_run_id=None,
                child_agent_id=None,
            )
            await session.refresh(parent)

            assert recovered.completed is True
            assert parent.status == "done"
            closeout_actions = (
                (
                    await session.execute(
                        select(ActivityLog.action).where(
                            ActivityLog.entity_id == parent.id,
                            ActivityLog.action.in_(
                                (
                                    "issue.child_outputs_closeout_failed",
                                    "issue.child_outputs_closeout_completed",
                                )
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert closeout_actions.count("issue.child_outputs_closeout_failed") == 1
            assert closeout_actions.count("issue.child_outputs_closeout_completed") == 1
    finally:
        await engine.dispose()
