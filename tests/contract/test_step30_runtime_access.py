from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from packages.database.clients import (
    async_write_transaction,
    create_database_engine,
    create_session_factory,
)
from packages.database.queries.organizations import create_organization
from packages.database.schema import Agent, Base, HeartbeatRun
from server.access import AccessDeniedError
from server.auth import RunTokenAuth, RunTokenConfig, RunTokenIssuer
from server.identity import PrincipalRef
from server.identity.system_access import SystemOperationAccess
from server.membership import MemberService
from server.services.runtime_access import RuntimeAccessResolver


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with value.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield value
    finally:
        await value.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return create_session_factory(engine)


async def test_run_token_is_bound_to_active_run_agent_and_membership(
    session_factory: async_sessionmaker,
) -> None:
    config = RunTokenConfig(
        secret="test-run-secret",
        issuer="test-control",
        audience="test-api",
        ttl_seconds=300,
    )
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id, agent, run = await _seed_running_run(session)
            token = RunTokenIssuer(config).issue(
                agent_id=agent.id,
                org_id=org_id,
                adapter_type=agent.agent_runtime_type,
                run_id=run.id,
            )

            authenticated = await RunTokenAuth(session, config).authenticate(
                f"Bearer {token}"
            )
            assert authenticated is not None
            assert authenticated.principal == PrincipalRef(type="agent", id=agent.id)
            assert authenticated.org_id == org_id
            assert authenticated.run_id == run.id

            run.status = "succeeded"
            await session.flush()
            assert (
                await RunTokenAuth(session, config).authenticate(f"Bearer {token}")
                is None
            )


async def test_runtime_access_resolver_injects_only_supported_run_credentials(
    session_factory: async_sessionmaker,
) -> None:
    config = RunTokenConfig(secret="runtime-secret")
    async with session_factory() as session:
        supported = SimpleNamespace(type="codex_local", supports_local_agent_jwt=True)
        resolved = await RuntimeAccessResolver(
            session, run_tokens=RunTokenIssuer(config)
        ).resolve(
            adapter=supported,  # type: ignore[arg-type]
            run_id="run-1",
            agent_id="agent-1",
            org_id="org-1",
            runtime_type="process",
            config={"model": "test"},
            env={"OCTOPUS_API_URL": "http://control.test"},
        )
        assert resolved.config == {"model": "test"}
        assert resolved.env is not None
        assert resolved.env["RUDDER_API_KEY"]
        assert resolved.env["RUDDER_API_URL"] == "http://control.test"

        unsupported = SimpleNamespace(type="http", supports_local_agent_jwt=False)
        without_token = await RuntimeAccessResolver(session).resolve(
            adapter=unsupported,  # type: ignore[arg-type]
            run_id="run-1",
            agent_id="agent-1",
            org_id="org-1",
            runtime_type="process",
            config={},
            env={
                "RUDDER_API_KEY": "stale",
                "RUDDER_API_URL": "http://stale.test",
            },
        )
        assert without_token.env is None


def test_system_operation_access_enforces_registered_capabilities() -> None:
    access = SystemOperationAccess()
    context = access.require(
        system_id="run_recovery",
        org_id="org-1",
        permission="runs:recover",
        reason="Recover a Run",
        entity_type="run",
        entity_id="run-1",
    )
    assert context.org_id == "org-1"
    assert context.entity_id == "run-1"

    with pytest.raises(AccessDeniedError, match="Missing permission"):
        access.require(
            system_id="run_dispatch",
            org_id="org-1",
            permission="runs:recover",
            reason="Invalid operation",
            entity_type="run",
            entity_id="run-1",
        )


async def _seed_running_run(
    session: AsyncSession,
) -> tuple[str, Agent, HeartbeatRun]:
    org_id = str(uuid5(NAMESPACE_URL, "octopus-test:run-access"))
    await create_organization(
        session,
        id=org_id,
        url_key="run-access",
        name="Run Access",
        issue_prefix="RAC",
    )
    agent = Agent(
        org_id=org_id,
        name="Engineer",
        role="engineer",
        agent_runtime_type="codex_local",
    )
    session.add(agent)
    await session.flush()
    await MemberService(session).ensure(org_id, PrincipalRef(type="agent", id=agent.id))
    run = HeartbeatRun(
        org_id=org_id,
        agent_id=agent.id,
        status="running",
    )
    session.add(run)
    await session.flush()
    return org_id, agent, run
