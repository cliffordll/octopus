from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import AgentWakeupRequest, HeartbeatRun, HeartbeatRunEvent


async def create_wakeup_request(
    session: AsyncSession, fields: Mapping[str, Any]
) -> AgentWakeupRequest:
    row = AgentWakeupRequest(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def create_wakeup_request_idempotent(
    session: AsyncSession, fields: Mapping[str, Any]
) -> tuple[AgentWakeupRequest, bool]:
    values = dict(fields)
    idempotency_key = values.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        return await create_wakeup_request(session, values), True
    try:
        async with session.begin_nested():
            row = AgentWakeupRequest(**values)
            session.add(row)
            await session.flush()
        return row, True
    except IntegrityError:
        result = await session.execute(
            select(AgentWakeupRequest).where(
                AgentWakeupRequest.org_id == values["org_id"],
                AgentWakeupRequest.agent_id == values["agent_id"],
                AgentWakeupRequest.idempotency_key == idempotency_key,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise
        return existing, False


async def update_wakeup_request(
    session: AsyncSession, wakeup_id: str, fields: Mapping[str, Any]
) -> AgentWakeupRequest | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(AgentWakeupRequest)
        .where(AgentWakeupRequest.id == wakeup_id)
        .values(**values)
        .returning(AgentWakeupRequest)
    )
    return result.scalar_one_or_none()


async def get_wakeup_by_idempotency_key(
    session: AsyncSession, agent_id: str, idempotency_key: str
) -> AgentWakeupRequest | None:
    result = await session.execute(
        select(AgentWakeupRequest)
        .where(
            AgentWakeupRequest.agent_id == agent_id,
            AgentWakeupRequest.idempotency_key == idempotency_key,
        )
        .order_by(AgentWakeupRequest.requested_at.desc(), AgentWakeupRequest.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_wakeup_requests_by_status(
    session: AsyncSession, agent_id: str, status: str
) -> Sequence[AgentWakeupRequest]:
    result = await session.execute(
        select(AgentWakeupRequest)
        .where(
            AgentWakeupRequest.agent_id == agent_id,
            AgentWakeupRequest.status == status,
        )
        .order_by(AgentWakeupRequest.requested_at, AgentWakeupRequest.id)
    )
    return result.scalars().all()


async def list_pending_runless_wakeup_requests(
    session: AsyncSession,
    org_id: str,
    agent_id: str,
    now: datetime,
) -> Sequence[AgentWakeupRequest]:
    result = await session.execute(
        select(AgentWakeupRequest)
        .where(
            AgentWakeupRequest.org_id == org_id,
            AgentWakeupRequest.agent_id == agent_id,
            AgentWakeupRequest.status.in_(("queued", "deferred_issue_execution")),
            AgentWakeupRequest.run_id.is_(None),
            AgentWakeupRequest.requested_at <= now,
        )
        .order_by(AgentWakeupRequest.requested_at, AgentWakeupRequest.id)
    )
    return result.scalars().all()


async def list_due_wakeup_request_ids(
    session: AsyncSession, status: str, now: datetime
) -> Sequence[str]:
    result = await session.scalars(
        select(AgentWakeupRequest.id)
        .where(
            AgentWakeupRequest.status == status,
            AgentWakeupRequest.requested_at <= now,
        )
        .order_by(AgentWakeupRequest.requested_at, AgentWakeupRequest.id)
    )
    return result.all()


async def claim_due_wakeup_request(
    session: AsyncSession, wakeup_id: str, status: str, claimed_at: datetime
) -> AgentWakeupRequest | None:
    result = await session.execute(
        update(AgentWakeupRequest)
        .where(
            AgentWakeupRequest.id == wakeup_id,
            AgentWakeupRequest.status == status,
            AgentWakeupRequest.run_id.is_(None),
            AgentWakeupRequest.requested_at <= claimed_at,
        )
        .values(
            status="claimed",
            claimed_at=claimed_at,
            updated_at=claimed_at,
        )
        .returning(AgentWakeupRequest)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none()


async def claim_parent_deferred_wakeup(
    session: AsyncSession, wakeup_id: str, claimed_at: datetime
) -> AgentWakeupRequest | None:
    result = await session.execute(
        update(AgentWakeupRequest)
        .where(
            AgentWakeupRequest.id == wakeup_id,
            AgentWakeupRequest.status == "deferred_parent_yield",
        )
        .values(status="claimed", claimed_at=claimed_at, updated_at=claimed_at)
        .returning(AgentWakeupRequest)
        .execution_options(synchronize_session=False, populate_existing=True)
    )
    return result.scalar_one_or_none()


async def create_run(session: AsyncSession, fields: Mapping[str, Any]) -> HeartbeatRun:
    row = HeartbeatRun(**dict(fields))
    session.add(row)
    await session.flush()
    return row


async def get_run(session: AsyncSession, run_id: str) -> HeartbeatRun | None:
    return await session.get(HeartbeatRun, run_id)


async def list_runs(
    session: AsyncSession, org_id: str, agent_id: str | None = None
) -> Sequence[HeartbeatRun]:
    statement = select(HeartbeatRun).where(HeartbeatRun.org_id == org_id)
    if agent_id is not None:
        statement = statement.where(HeartbeatRun.agent_id == agent_id)
    result = await session.execute(
        statement.order_by(HeartbeatRun.created_at.desc(), HeartbeatRun.id.desc())
    )
    return result.scalars().all()


async def update_run(
    session: AsyncSession, run_id: str, fields: Mapping[str, Any]
) -> HeartbeatRun | None:
    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)
    result = await session.execute(
        update(HeartbeatRun)
        .where(HeartbeatRun.id == run_id)
        .values(**values)
        .returning(HeartbeatRun)
    )
    return result.scalar_one_or_none()


async def list_running_run_ids(session: AsyncSession, agent_id: str) -> set[str]:
    result = await session.scalars(
        select(HeartbeatRun.id).where(
            HeartbeatRun.agent_id == agent_id,
            HeartbeatRun.status == "running",
        )
    )
    return set(result.all())


async def has_active_timer_run(session: AsyncSession, agent_id: str) -> bool:
    result = await session.scalars(
        select(HeartbeatRun.id)
        .where(
            HeartbeatRun.agent_id == agent_id,
            HeartbeatRun.invocation_source == "timer",
            HeartbeatRun.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    return result.first() is not None


async def has_active_agent_run(session: AsyncSession, agent_id: str) -> bool:
    result = await session.scalars(
        select(HeartbeatRun.id)
        .where(
            HeartbeatRun.agent_id == agent_id,
            HeartbeatRun.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    return result.first() is not None


async def list_runs_by_status(
    session: AsyncSession, status: str
) -> Sequence[HeartbeatRun]:
    result = await session.execute(
        select(HeartbeatRun)
        .where(HeartbeatRun.status == status)
        .order_by(HeartbeatRun.created_at, HeartbeatRun.id)
    )
    return result.scalars().all()


async def list_queued_runs(
    session: AsyncSession, agent_id: str
) -> Sequence[HeartbeatRun]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(HeartbeatRun)
        .outerjoin(
            AgentWakeupRequest,
            HeartbeatRun.wakeup_request_id == AgentWakeupRequest.id,
        )
        .where(
            HeartbeatRun.agent_id == agent_id,
            HeartbeatRun.status == "queued",
            or_(
                HeartbeatRun.wakeup_request_id.is_(None),
                and_(
                    AgentWakeupRequest.status == "queued",
                    AgentWakeupRequest.requested_at <= now,
                ),
            ),
        )
        .order_by(HeartbeatRun.created_at, HeartbeatRun.id)
    )
    return result.scalars().all()


async def list_queued_agent_ids(session: AsyncSession) -> set[str]:
    result = await session.scalars(
        select(HeartbeatRun.agent_id)
        .outerjoin(
            AgentWakeupRequest,
            HeartbeatRun.wakeup_request_id == AgentWakeupRequest.id,
        )
        .where(
            HeartbeatRun.status == "queued",
            or_(
                HeartbeatRun.wakeup_request_id.is_(None),
                and_(
                    AgentWakeupRequest.status == "queued",
                    AgentWakeupRequest.requested_at <= datetime.now(UTC),
                ),
            ),
        )
        .distinct()
    )
    return set(result.all())


async def claim_queued_run(
    session: AsyncSession, run_id: str, started_at: datetime
) -> HeartbeatRun | None:
    owner_token = str(uuid4())
    result = await session.execute(
        update(HeartbeatRun)
        .where(HeartbeatRun.id == run_id, HeartbeatRun.status == "queued")
        .values(
            status="running",
            started_at=started_at,
            execution_owner_token=owner_token,
            execution_lease_expires_at=started_at + timedelta(minutes=5),
            updated_at=started_at,
        )
        .returning(HeartbeatRun)
        .execution_options(synchronize_session=False, populate_existing=True)
    )
    return result.scalar_one_or_none()


async def renew_run_execution_lease(
    session: AsyncSession,
    run_id: str,
    owner_token: str,
    *,
    now: datetime | None = None,
) -> bool:
    renewed_at = now or datetime.now(UTC)
    result = await session.execute(
        update(HeartbeatRun)
        .where(
            HeartbeatRun.id == run_id,
            HeartbeatRun.status == "running",
            HeartbeatRun.execution_owner_token == owner_token,
        )
        .values(execution_lease_expires_at=renewed_at + timedelta(minutes=5))
        .returning(HeartbeatRun.id)
    )
    return result.scalar_one_or_none() is not None


async def request_run_yield(
    session: AsyncSession,
    run_id: str,
    owner_token: str,
    requested_at: datetime,
) -> HeartbeatRun | None:
    """Persist a parent handoff request without releasing its execution lease."""

    result = await session.execute(
        update(HeartbeatRun)
        .where(
            HeartbeatRun.id == run_id,
            HeartbeatRun.status == "running",
            HeartbeatRun.execution_owner_token == owner_token,
            HeartbeatRun.yield_requested_at.is_(None),
        )
        .values(
            yield_requested_at=requested_at,
            updated_at=requested_at,
        )
        .returning(HeartbeatRun)
        .execution_options(synchronize_session=False, populate_existing=True)
    )
    return result.scalar_one_or_none()


async def claim_expired_run_execution(
    session: AsyncSession, run_id: str, *, now: datetime | None = None
) -> HeartbeatRun | None:
    claimed_at = now or datetime.now(UTC)
    owner_token = str(uuid4())
    result = await session.execute(
        update(HeartbeatRun)
        .where(
            HeartbeatRun.id == run_id,
            HeartbeatRun.status == "running",
            or_(
                HeartbeatRun.execution_lease_expires_at.is_(None),
                HeartbeatRun.execution_lease_expires_at <= claimed_at,
            ),
        )
        .values(
            execution_owner_token=owner_token,
            execution_lease_expires_at=claimed_at + timedelta(minutes=5),
            updated_at=claimed_at,
        )
        .execution_options(synchronize_session=False, populate_existing=True)
        .returning(HeartbeatRun)
    )
    return result.scalar_one_or_none()


async def transition_run_to_terminal(
    session: AsyncSession,
    run_id: str,
    status: str,
    fields: Mapping[str, Any],
    *,
    expected_statuses: Sequence[str] = ("running",),
    expected_owner_token: str | None = None,
    terminal_effects: Mapping[str, Any] | None = None,
) -> HeartbeatRun | None:
    now = datetime.now(UTC)
    conditions = [
        HeartbeatRun.id == run_id,
        HeartbeatRun.status.in_(tuple(expected_statuses)),
    ]
    if expected_owner_token is not None:
        conditions.append(HeartbeatRun.execution_owner_token == expected_owner_token)
    values = dict(fields)
    values.update(
        {
            "status": status,
            "finished_at": values.get("finished_at") or now,
            "execution_owner_token": None,
            "execution_lease_expires_at": None,
            "terminal_effects_pending": True,
            "terminal_effects_json": dict(
                terminal_effects
                or {
                    "version": 1,
                    "effects": [
                        "runtime_state",
                        "agent_status",
                        "issue_release",
                        "workspace_release",
                        "lifecycle_event",
                    ],
                }
            ),
            "terminal_effects_completed_json": None,
            "terminal_effects_dead_lettered_json": None,
            "terminal_effects_attempts_json": {},
            "terminal_effects_next_attempt_at": None,
            "terminal_effects_dead_lettered_at": None,
            "terminal_effects_claim_token": None,
            "terminal_effects_claimed_at": None,
            "terminal_effects_attempt_count": 0,
            "terminal_effects_last_error": None,
            "updated_at": now,
        }
    )
    result = await session.execute(
        update(HeartbeatRun)
        .where(and_(*conditions))
        .values(**values)
        .returning(HeartbeatRun)
    )
    run = result.scalar_one_or_none()
    if run is None or run.wakeup_request_id is None:
        return run
    wakeup_status = (
        "completed" if status in {"succeeded", "waiting_for_children"} else status
    )
    await session.execute(
        update(AgentWakeupRequest)
        .where(
            AgentWakeupRequest.id == run.wakeup_request_id,
            AgentWakeupRequest.status.not_in(
                (
                    "completed",
                    "failed",
                    "cancelled",
                    "timed_out",
                    "skipped",
                    "coalesced",
                )
            ),
        )
        .values(
            status=wakeup_status,
            finished_at=run.finished_at,
            error=run.error,
            updated_at=now,
        )
    )
    return run


async def list_runs_with_pending_terminal_effects(
    session: AsyncSession, *, now: datetime | None = None
) -> Sequence[HeartbeatRun]:
    checked_at = now or datetime.now(UTC)
    result = await session.execute(
        select(HeartbeatRun)
        .where(
            HeartbeatRun.terminal_effects_pending.is_(True),
            or_(
                HeartbeatRun.terminal_effects_next_attempt_at.is_(None),
                HeartbeatRun.terminal_effects_next_attempt_at <= checked_at,
            ),
        )
        .order_by(HeartbeatRun.updated_at, HeartbeatRun.id)
    )
    return result.scalars().all()


async def claim_run_terminal_effects(
    session: AsyncSession, run_id: str, *, now: datetime | None = None
) -> HeartbeatRun | None:
    claimed_at = now or datetime.now(UTC)
    stale_before = claimed_at - timedelta(minutes=5)
    claim_token = str(uuid4())
    result = await session.execute(
        update(HeartbeatRun)
        .where(
            HeartbeatRun.id == run_id,
            HeartbeatRun.terminal_effects_pending.is_(True),
            or_(
                HeartbeatRun.terminal_effects_next_attempt_at.is_(None),
                HeartbeatRun.terminal_effects_next_attempt_at <= claimed_at,
            ),
            or_(
                HeartbeatRun.terminal_effects_claim_token.is_(None),
                HeartbeatRun.terminal_effects_claimed_at.is_(None),
                HeartbeatRun.terminal_effects_claimed_at <= stale_before,
            ),
        )
        .values(
            terminal_effects_claim_token=claim_token,
            terminal_effects_claimed_at=claimed_at,
            terminal_effects_attempt_count=HeartbeatRun.terminal_effects_attempt_count
            + 1,
            updated_at=claimed_at,
        )
        .execution_options(synchronize_session=False, populate_existing=True)
        .returning(HeartbeatRun)
    )
    return result.scalar_one_or_none()


async def complete_run_terminal_effects(
    session: AsyncSession, run_id: str, claim_token: str, effects: Sequence[str]
) -> HeartbeatRun | None:
    result = await session.execute(
        update(HeartbeatRun)
        .where(
            HeartbeatRun.id == run_id,
            HeartbeatRun.terminal_effects_pending.is_(True),
            HeartbeatRun.terminal_effects_claim_token == claim_token,
        )
        .values(
            terminal_effects_pending=False,
            terminal_effects_json=None,
            terminal_effects_completed_json=list(effects),
            terminal_effects_claim_token=None,
            terminal_effects_claimed_at=None,
            terminal_effects_next_attempt_at=None,
            terminal_effects_last_error=None,
            updated_at=datetime.now(UTC),
        )
        .returning(HeartbeatRun)
    )
    return result.scalar_one_or_none()


async def fail_run_terminal_effects(
    session: AsyncSession, run_id: str, claim_token: str, error: str
) -> None:
    now = datetime.now(UTC)
    await session.execute(
        update(HeartbeatRun)
        .where(
            HeartbeatRun.id == run_id,
            HeartbeatRun.terminal_effects_pending.is_(True),
            HeartbeatRun.terminal_effects_claim_token == claim_token,
        )
        .values(
            terminal_effects_claim_token=None,
            terminal_effects_claimed_at=None,
            terminal_effects_next_attempt_at=now + timedelta(seconds=5),
            terminal_effects_last_error=error[:4000],
            updated_at=now,
        )
    )


async def append_run_event(
    session: AsyncSession, fields: Mapping[str, Any]
) -> HeartbeatRunEvent:
    values = dict(fields)
    idempotency_key = values.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        row = HeartbeatRunEvent(**values)
        session.add(row)
        await session.flush()
        return row
    try:
        async with session.begin_nested():
            row = HeartbeatRunEvent(**values)
            session.add(row)
            await session.flush()
        return row
    except IntegrityError:
        result = await session.execute(
            select(HeartbeatRunEvent).where(
                HeartbeatRunEvent.run_id == values["run_id"],
                HeartbeatRunEvent.idempotency_key == idempotency_key,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise
        return existing


async def list_run_events(
    session: AsyncSession, run_id: str, after_seq: int = 0, limit: int = 200
) -> Sequence[HeartbeatRunEvent]:
    result = await session.execute(
        select(HeartbeatRunEvent)
        .where(
            HeartbeatRunEvent.run_id == run_id,
            HeartbeatRunEvent.seq > after_seq,
        )
        .order_by(HeartbeatRunEvent.seq, HeartbeatRunEvent.id)
        .limit(limit)
    )
    return result.scalars().all()
