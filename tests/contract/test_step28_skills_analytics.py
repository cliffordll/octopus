from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import (
    ActivityLog,
    Agent,
    Base,
    HeartbeatRun,
    HeartbeatRunEvent,
    Organization,
)
from server.app import create_app


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    try:
        yield application, factory
    finally:
        await engine.dispose()


async def _request(app: FastAPI, path: str) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(path)
    return response.status_code, response.json()


async def test_agent_skills_analytics_counts_persisted_evidence(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    other_agent_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    old = now - timedelta(days=60)

    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"skills-{uuid.uuid4().hex[:8]}",
                name="Skills Org",
                issue_prefix=f"SK{uuid.uuid4().hex[:4].upper()}",
            )
        )
        for current_agent_id, name in [
            (agent_id, "Skills Agent"),
            (other_agent_id, "Other Agent"),
        ]:
            session.add(
                Agent(
                    id=current_agent_id,
                    org_id=org_id,
                    name=name,
                    workspace_key=current_agent_id,
                    role="engineer",
                    agent_runtime_type="codex_local",
                )
            )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="manual",
                status="succeeded",
                context_snapshot={"desiredSkills": ["review"]},
                result_json={"loadedSkills": ["review"]},
                created_at=now,
            )
        )
        session.add(
            HeartbeatRunEvent(
                org_id=org_id,
                run_id=run_id,
                agent_id=agent_id,
                seq=1,
                event_type="runtime",
                payload={"skills": {"used": ["review"], "requested": ["debug"]}},
                created_at=now,
            )
        )
        session.add(
            ActivityLog(
                org_id=org_id,
                actor_type="agent",
                actor_id=agent_id,
                action="agent.skills_used",
                entity_type="agent",
                entity_id=agent_id,
                agent_id=agent_id,
                run_id=run_id,
                details={"skillEvidence": [{"skill": "review", "kind": "used"}]},
                created_at=now,
            )
        )
        session.add(
            ActivityLog(
                org_id=org_id,
                actor_type="agent",
                actor_id=agent_id,
                action="agent.skills_used",
                entity_type="agent",
                entity_id=agent_id,
                agent_id=agent_id,
                details={"skillEvidence": [{"skill": "old", "kind": "used"}]},
                created_at=old,
            )
        )
        session.add(
            ActivityLog(
                org_id=org_id,
                actor_type="agent",
                actor_id=other_agent_id,
                action="agent.skills_used",
                entity_type="agent",
                entity_id=other_agent_id,
                agent_id=other_agent_id,
                details={"skillEvidence": [{"skill": "other", "kind": "used"}]},
                created_at=now,
            )
        )
        await session.commit()

    code, body = await _request(
        application, f"/api/agents/{agent_id}/skills/analytics?windowDays=30"
    )

    assert code == 200
    assert body["agentId"] == agent_id
    assert body["orgId"] == org_id
    assert body["totalCount"] == 5
    assert body["totalRunsWithSkills"] == 1
    assert body["evidenceCounts"] == {"used": 2, "requested": 2, "loaded": 1}
    by_skill = {item["skill"]: item for item in body["skills"]}
    assert by_skill["review"]["used"] == 2
    assert by_skill["review"]["requested"] == 1
    assert by_skill["review"]["loaded"] == 1
    assert by_skill["debug"]["requested"] == 1
    assert "old" not in by_skill
    assert "other" not in by_skill
    assert body["days"][0]["date"] == now.date().isoformat()
    assert body["days"][0]["used"] == 2
