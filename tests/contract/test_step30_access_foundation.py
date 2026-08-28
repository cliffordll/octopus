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
from packages.database.queries.permissions import replace_permissions
from packages.database.queries.organizations import create_organization
from packages.database.queries.users import ensure_user
from packages.database.schema import Base, Agent
from server.access import AccessPolicyService
from server.auth.root_provisioning import RootProvisioningService
from server.auth import LocalPasswordAuth
from server.identity import (
    ApprovalRequesterMapper,
    IssueAssigneeMapper,
    PrincipalRef,
    SystemIdentityContextFactory,
)
from server.identity.resolver import IdentityContextResolver
from server.organization_hierarchy import OrganizationHierarchyService
from server.roles import RoleAccessService, RoleService
from server.roles.management import RoleManagementService
from server.services.agents import AgentService


USE_REAL_ACCESS = True


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


def test_access_foundation_tables_use_unified_access_model() -> None:
    assert {"users", "roles", "permissions"}.issubset(Base.metadata.tables)

    roles = Base.metadata.tables["roles"]
    assert {
        "scope_type",
        "scope_id",
        "principal_type",
        "principal_id",
        "status",
        "role",
        "reports_to",
    }.issubset(roles.columns.keys())
    assert "roles_scope_principal_uq" in {
        constraint.name for constraint in roles.constraints
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
                        "('users', 'roles', 'permissions')"
                    )
                )
            }
            permission_indexes = {
                row[1]
                for row in await connection.execute(
                    text("pragma index_list(permissions)")
                )
            }
            role_columns = {
                row[1]
                for row in await connection.execute(text("pragma table_info(roles)"))
            }
            role_indexes = {
                row[1]
                for row in await connection.execute(text("pragma index_list(roles)"))
            }
    finally:
        await migrated_engine.dispose()

    assert table_names == {"users", "roles", "permissions"}
    assert "permissions_scope_key_idx" in permission_indexes
    assert "reports_to" in role_columns
    assert "roles_scope_reports_to_idx" in role_indexes


async def test_human_and_agent_share_organization_hierarchy(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, key="hierarchy")
            await _seed_user(session, "owner-user")
            await _seed_user(session, "manager-user")
            agent = Agent(org_id=org_id, name="Engineer", role="engineer")
            session.add(agent)
            await session.flush()

            roles = RoleService(session)
            owner = await roles.ensure(
                "organization",
                org_id,
                PrincipalRef(type="user", id="owner-user"),
                role="owner",
            )
            manager = await roles.ensure(
                "organization",
                org_id,
                PrincipalRef(type="user", id="manager-user"),
                role="member",
            )
            agent_role = await roles.ensure(
                "organization",
                org_id,
                PrincipalRef(type="agent", id=agent.id),
                role="member",
            )
            hierarchy = OrganizationHierarchyService(session)

            default_members = await hierarchy.list(org_id)
            assert (
                next(
                    item for item in default_members if item.role.id == manager.id
                ).reports_to
                == owner.id
            )
            updated = await hierarchy.set_manager(org_id, agent_role.id, manager.id)
            members = await hierarchy.list(org_id)

            assert updated.reports_to == manager.id
            assert {member.role.principal_type for member in members} == {
                "user",
                "agent",
            }
            assert (
                next(
                    item for item in members if item.role.id == agent_role.id
                ).reports_to
                == manager.id
            )


async def test_organization_hierarchy_rejects_reporting_cycles(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, key="hierarchy-cycle")
            await _seed_user(session, "cycle-owner")
            await _seed_user(session, "cycle-a")
            await _seed_user(session, "cycle-b")
            roles = RoleService(session)
            await roles.ensure(
                "organization",
                org_id,
                PrincipalRef(type="user", id="cycle-owner"),
                role="owner",
            )
            first = await roles.ensure(
                "organization",
                org_id,
                PrincipalRef(type="user", id="cycle-a"),
                role="member",
            )
            second = await roles.ensure(
                "organization",
                org_id,
                PrincipalRef(type="user", id="cycle-b"),
                role="member",
            )
            hierarchy = OrganizationHierarchyService(session)
            await hierarchy.set_manager(org_id, second.id, first.id)

            with pytest.raises(ValueError, match="cycle"):
                await hierarchy.set_manager(org_id, first.id, second.id)


async def test_user_and_agent_share_role_service(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session)
            await _seed_user(session, "user-1")
            agent = Agent(org_id=org_id, name="Engineer", role="engineer")
            session.add(agent)
            await session.flush()

            roles = RoleService(session)
            user_role = await roles.ensure(
                "organization",
                org_id,
                PrincipalRef(type="user", id="user-1"),
                role="owner",
            )
            agent_role = await roles.ensure(
                "organization",
                org_id,
                PrincipalRef(type="agent", id=agent.id),
                role="member",
            )
            duplicate = await roles.ensure(
                "organization",
                org_id,
                PrincipalRef(type="agent", id=agent.id),
                role="member",
            )

            assert user_role.principal_type == "user"
            assert agent_role.principal_type == "agent"
            assert duplicate.id == agent_role.id
            assert await RoleAccessService(roles).require_active(
                "organization", org_id, PrincipalRef(type="agent", id=agent.id)
            )


async def test_agent_creation_registers_role_and_default_permission(
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
                actor_type="user",
                actor_id="user-creator",
            )
            principal = PrincipalRef(type="agent", id=created["id"])
            access_role = await RoleService(session).get(
                "organization", org_id, principal
            )
            context = await IdentityContextResolver(session).resolve(
                actor_type="agent",
                actor_id=created["id"],
                org_id=org_id,
                source="test",
            )
            detail = await agents.get_detail(created["id"])

            assert access_role is not None
            assert access_role.status == "active"
            assert access_role.role == "member"
            assert context.permissions == frozenset({"tasks:assign"})
            assert detail is not None
            assert detail["access"]["role"] is not None
            assert detail["access"]["taskAssignSource"] == "explicit_grant"
            assert [
                permission["permissionKey"]
                for permission in detail["access"]["permissions"]
            ] == ["tasks:assign"]


async def test_role_service_rejects_cross_org_agent(
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
                await RoleService(session).ensure(
                    "organization",
                    second_org,
                    PrincipalRef(type="agent", id=agent.id),
                    role="member",
                )


async def test_context_resolver_combines_role_and_permissions(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session)
            agent = Agent(org_id=org_id, name="Reviewer", role="reviewer")
            session.add(agent)
            await session.flush()
            principal = PrincipalRef(type="agent", id=agent.id)
            await RoleService(session).ensure(
                "organization", org_id, principal, role="member"
            )
            await replace_permissions(
                session,
                scope_type="organization",
                scope_id=org_id,
                principal_type="agent",
                principal_id=agent.id,
                permissions=[{"permission_key": "tasks:assign", "constraints": None}],
                granted_by_user_id=None,
            )

            context = await IdentityContextResolver(session).resolve(
                actor_type="agent",
                actor_id=agent.id,
                org_id=org_id,
                source="test",
            )

            assert context.principal == principal
            assert context.has_active_role
            assert context.permissions == frozenset({"tasks:assign"})
            AccessPolicyService().require_permission(context, org_id, "tasks:assign")


async def test_permission_constraints_fail_closed_until_supported(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, key="constrained")
            await _seed_user(session, "constrained-user")
            principal = PrincipalRef(type="user", id="constrained-user")
            await RoleService(session).ensure(
                "organization", org_id, principal, role="member"
            )
            await replace_permissions(
                session,
                scope_type="organization",
                scope_id=org_id,
                principal_type="user",
                principal_id=principal.id,
                permissions=[
                    {
                        "permission_key": "tasks:assign",
                        "constraints": {"projectIds": ["project-1"]},
                    }
                ],
                granted_by_user_id=None,
            )
            context = await IdentityContextResolver(session).resolve(
                actor_type="user",
                actor_id=principal.id,
                org_id=org_id,
                source="test",
            )

            with pytest.raises(PermissionError, match="Missing permission"):
                AccessPolicyService().require_permission(
                    context, org_id, "tasks:assign"
                )


async def test_suspended_role_loses_access_immediately(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, key="suspended")
            await _seed_user(session, "suspended-user")
            principal = PrincipalRef(type="user", id="suspended-user")
            role = await RoleService(session).ensure(
                "organization", org_id, principal, role="member"
            )
            managed = await RoleManagementService(session).update_status(
                org_id, role.id, "suspended"
            )
            context = await IdentityContextResolver(session).resolve(
                actor_type="user",
                actor_id=principal.id,
                org_id=org_id,
                source="test",
            )

            assert managed is not None
            assert managed.role.status == "suspended"
            with pytest.raises(PermissionError):
                AccessPolicyService().require_organization_access(context, org_id)


async def test_root_provisioning_creates_explicit_root_role(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            user_id = await RootProvisioningService(session).create(
                name="Root User",
                email="root@example.com",
                password="secure-password",
            )
            context = await IdentityContextResolver(session).resolve(
                actor_type="user",
                actor_id=user_id,
                org_id=None,
                source="session",
            )

            assert context.principal == PrincipalRef(type="user", id=user_id)
            assert context.is_root


async def test_root_provisioning_promotes_an_existing_local_account(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            user_id, _token = await LocalPasswordAuth(session).register(
                name="Existing User",
                email="existing@example.com",
                password="secure-password",
            )
            promoted_id = await RootProvisioningService(session).create(
                name="Ignored Name",
                email="existing@example.com",
                password="secure-password",
            )
            context = await IdentityContextResolver(session).resolve(
                actor_type="user",
                actor_id=user_id,
                org_id=None,
                source="test",
            )

            assert promoted_id == user_id
            assert context.is_root


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
