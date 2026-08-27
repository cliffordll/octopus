from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from packages.database.clients import (
    async_write_transaction,
    create_database_engine,
    create_session_factory,
)
from packages.database.migrations.runner import upgrade_to_head
from packages.database.queries.access import (
    replace_principal_permission_grants,
)
from packages.database.queries.organizations import create_organization
from packages.database.queries.users import ensure_user
from packages.database.schema import Base, Agent
from server.access import AccessPolicyService
from server.identity import (
    ApprovalRequesterMapper,
    IdentityContextResolver,
    IssueAssigneeMapper,
    LocalAccessBootstrapService,
    PrincipalRef,
    SystemIdentityContextFactory,
)
from server.membership import MemberAccessService, MemberService
from server.services.agents import AgentService


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


def test_access_foundation_tables_match_upstream_contract() -> None:
    assert {
        "user",
        "organization_memberships",
        "principal_permission_grants",
        "instance_user_roles",
    }.issubset(Base.metadata.tables)

    membership = Base.metadata.tables["organization_memberships"]
    assert {
        "org_id",
        "principal_type",
        "principal_id",
        "status",
        "membership_role",
    }.issubset(membership.columns.keys())
    assert "organization_memberships_org_principal_unique_idx" in {
        constraint.name for constraint in membership.constraints
    }


async def test_access_foundation_migration_creates_compatible_tables(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'access.db'}"
    await upgrade_to_head(database_url)

    migrated_engine = create_database_engine(database_url)
    try:
        async with migrated_engine.connect() as connection:
            table_names = {
                row[0]
                for row in await connection.execute(
                    text(
                        "select name from sqlite_master "
                        "where type='table' and name in "
                        "('user', 'organization_memberships', "
                        "'principal_permission_grants', 'instance_user_roles')"
                    )
                )
            }
            permission_indexes = {
                row[1]
                for row in await connection.execute(
                    text("pragma index_list(principal_permission_grants)")
                )
            }
    finally:
        await migrated_engine.dispose()

    assert table_names == {
        "user",
        "organization_memberships",
        "principal_permission_grants",
        "instance_user_roles",
    }
    assert "principal_permission_grants_company_permission_idx" in permission_indexes


async def test_user_and_agent_share_membership_service(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session)
            await _seed_user(session, "user-1")
            agent = Agent(org_id=org_id, name="Engineer", role="engineer")
            session.add(agent)
            await session.flush()

            members = MemberService(session)
            user_membership = await members.ensure(
                org_id,
                PrincipalRef(type="user", id="user-1"),
                role="owner",
            )
            agent_membership = await members.ensure(
                org_id,
                PrincipalRef(type="agent", id=agent.id),
            )
            duplicate = await members.ensure(
                org_id,
                PrincipalRef(type="agent", id=agent.id),
            )

            assert user_membership.principal_type == "user"
            assert agent_membership.principal_type == "agent"
            assert duplicate.id == agent_membership.id
            assert await MemberAccessService(members).require_active(
                org_id, PrincipalRef(type="agent", id=agent.id)
            )


async def test_agent_creation_registers_membership_and_default_grant(
    session_factory: async_sessionmaker,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path))
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, key="created-agent")
            agents = AgentService(session)
            created = await agents.create_agent(
                org_id,
                {"name": "Engineer", "role": "engineer"},
                actor_type="board",
                actor_id="local-board",
            )
            principal = PrincipalRef(type="agent", id=created["id"])
            membership = await MemberService(session).get(org_id, principal)
            context = await IdentityContextResolver(session).resolve(
                actor_type="agent",
                actor_id=created["id"],
                org_id=org_id,
                source="test",
            )
            detail = await agents.get_detail(created["id"])

            assert membership is not None
            assert membership.status == "active"
            assert membership.membership_role == "member"
            assert context.permissions == frozenset({"tasks:assign"})
            assert detail is not None
            assert detail["access"]["membership"] is not None
            assert detail["access"]["taskAssignSource"] == "explicit_grant"
            assert [grant["permissionKey"] for grant in detail["access"]["grants"]] == [
                "tasks:assign"
            ]


async def test_member_service_rejects_cross_org_agent(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            first_org = await _seed_org(session, key="first")
            second_org = await _seed_org(session, key="second")
            agent = Agent(org_id=first_org, name="Engineer", role="engineer")
            session.add(agent)
            await session.flush()

            with pytest.raises(ValueError, match="another organization"):
                await MemberService(session).ensure(
                    second_org,
                    PrincipalRef(type="agent", id=agent.id),
                )


async def test_context_resolver_combines_membership_and_permissions(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session)
            agent = Agent(org_id=org_id, name="Reviewer", role="reviewer")
            session.add(agent)
            await session.flush()
            principal = PrincipalRef(type="agent", id=agent.id)
            await MemberService(session).ensure(org_id, principal)
            await replace_principal_permission_grants(
                session,
                org_id=org_id,
                principal_type="agent",
                principal_id=agent.id,
                grants=[{"permission_key": "tasks:assign", "scope": None}],
                granted_by_user_id=None,
            )

            context = await IdentityContextResolver(session).resolve(
                actor_type="agent",
                actor_id=agent.id,
                org_id=org_id,
                source="test",
            )

            assert context.principal == principal
            assert context.has_active_membership
            assert context.permissions == frozenset({"tasks:assign"})
            AccessPolicyService().require_permission(context, org_id, "tasks:assign")


async def test_local_bootstrap_creates_real_board_access(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session)
            await LocalAccessBootstrapService(session).ensure()
            context = await IdentityContextResolver(session).resolve(
                actor_type="board",
                actor_id="local-board",
                org_id=org_id,
                source="local_implicit",
            )

            assert context.principal == PrincipalRef(type="user", id="local-board")
            assert context.membership_role == "owner"
            assert context.is_instance_admin
            assert AccessPolicyService().can_access_organization(context, org_id)


def test_principal_mappers_keep_compatibility_fields_encapsulated() -> None:
    principal = PrincipalRef(type="agent", id="agent-1")
    values = IssueAssigneeMapper.write_values(principal)
    assert values == {
        "assignee_user_id": None,
        "assignee_agent_id": "agent-1",
    }
    assert IssueAssigneeMapper.read(values) == principal

    with pytest.raises(ValueError, match="Both"):
        ApprovalRequesterMapper.read(
            {
                "requested_by_user_id": "user-1",
                "requested_by_agent_id": "agent-1",
            }
        )


def test_system_context_factory_rejects_unregistered_principal() -> None:
    factory = SystemIdentityContextFactory()
    context = factory.create(
        system_id="run_recovery",
        org_id="org-1",
        reason="recover orphan",
        entity_type="run",
        entity_id="run-1",
    )
    assert context.principal == PrincipalRef(type="system", id="run_recovery")
    assert "runs:recover" in context.permissions

    with pytest.raises(ValueError, match="Unregistered"):
        factory.create(
            system_id="unknown",
            org_id="org-1",
            reason="test",
            entity_type="run",
            entity_id="run-1",
        )


async def _seed_org(session: AsyncSession, key: str = "access") -> str:
    org_id = str(uuid5(NAMESPACE_URL, f"octopus-test:{key}"))
    await create_organization(
        session,
        id=org_id,
        url_key=f"org-{key}",
        name=f"Organization {key}",
        issue_prefix=key[:6].upper(),
    )
    return org_id


async def _seed_user(session: AsyncSession, user_id: str) -> None:
    now = datetime.now(UTC)
    await ensure_user(
        session,
        {
            "id": user_id,
            "name": user_id,
            "email": f"{user_id}@example.invalid",
            "email_verified": True,
            "created_at": now,
            "updated_at": now,
        },
    )
