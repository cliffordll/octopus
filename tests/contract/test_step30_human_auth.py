from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
import time
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from packages.database.clients import (
    async_write_transaction,
    create_database_engine,
    create_session_factory,
)
from packages.database.queries.external_identities import ensure_external_identity
from packages.database.queries.organizations import create_organization
from packages.database.queries.users import ensure_user
from packages.database.schema import Base
from server.access import PermissionSpec
from server.auth import LocalPasswordAuth, PasswordHasher, ProxyTokenAuth, SessionAuth
from server.identity import PrincipalRef
from server.identity.resolver import IdentityContextResolver
from server.dependencies.identity import get_identity_context
from server.invitations import InvitationService
from server.roles import RoleManagementService, RoleService


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


def test_human_auth_tables_use_consistent_plural_names() -> None:
    assert {
        "sessions",
        "credentials",
        "verifications",
        "external_identities",
        "invites",
    }.issubset(Base.metadata.tables)
    assert {"expires_at", "token", "user_id"}.issubset(
        Base.metadata.tables["sessions"].columns.keys()
    )
    assert {"account_id", "provider_id", "password_hash"}.issubset(
        Base.metadata.tables["credentials"].columns.keys()
    )


def test_password_hasher_never_stores_plaintext() -> None:
    hasher = PasswordHasher()
    encoded = hasher.hash("correct-horse-battery-staple")
    assert "correct-horse" not in encoded
    assert hasher.verify("correct-horse-battery-staple", encoded)
    assert not hasher.verify("wrong-password", encoded)


def test_email_auth_routes_issue_http_only_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "human-auth.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("OCTOPUS_AUTO_MIGRATE", "1")
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "0")
    monkeypatch.setenv("OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED", "0")

    from server.app import create_app

    with TestClient(create_app()) as client:
        registered = client.post(
            "/api/auth/sign-up/email",
            json={
                "name": "Alice",
                "email": "alice@example.com",
                "password": "secure-password",
            },
        )
        session_response = client.get("/api/auth/get-session")
        rejected_sign_out = client.post("/api/auth/sign-out")
        signed_out = client.post(
            "/api/auth/sign-out", headers={"origin": "http://testserver"}
        )
        missing_session = client.get("/api/auth/get-session")

    assert registered.status_code == 201
    assert "HttpOnly" in registered.headers["set-cookie"]
    assert session_response.status_code == 200
    assert session_response.json()["user"]["email"] == "alice@example.com"
    assert rejected_sign_out.status_code == 403
    assert signed_out.status_code == 200
    assert missing_session.json() is None


def test_organization_owner_can_manage_members_and_invites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "member-management.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("OCTOPUS_AUTO_MIGRATE", "1")
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "0")
    monkeypatch.setenv("OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED", "0")

    from server.app import create_app

    with TestClient(create_app()) as client:
        registered = client.post(
            "/api/auth/sign-up/email",
            json={
                "name": "Owner",
                "email": "owner@example.com",
                "password": "secure-password",
            },
        )
        organization = client.post(
            "/api/orgs",
            json={"name": "Team"},
            headers={"origin": "http://testserver"},
        ).json()
        org_id = organization["id"]
        members = client.get(f"/api/orgs/{org_id}/members")
        hierarchy = client.get(f"/api/orgs/{org_id}/hierarchy")
        created = client.post(
            f"/api/orgs/{org_id}/invites",
            json={"allowedJoinTypes": "human"},
            headers={"origin": "http://testserver"},
        )
        inspected = client.get(f"/api/invites/{created.json()['token']}")

    assert members.status_code == 200
    assert registered.status_code == 201
    assert members.json()[0]["principalId"] == registered.json()["user"]["id"]
    assert members.json()[0]["displayName"]
    assert isinstance(members.json()[0]["permissions"], list)
    assert hierarchy.status_code == 200
    assert hierarchy.json() == [
        {
            "id": members.json()[0]["id"],
            "orgId": org_id,
            "principalType": "user",
            "principalId": registered.json()["user"]["id"],
            "displayName": members.json()[0]["displayName"],
            "status": "active",
            "role": "owner",
            "reportsTo": None,
        }
    ]
    assert created.status_code == 201
    assert inspected.status_code == 200
    assert inspected.json()["allowedJoinTypes"] == "human"


def test_local_trusted_does_not_create_an_implicit_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "local-cookie.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("OCTOPUS_AUTO_MIGRATE", "1")
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED", "0")

    from server.app import create_app

    with TestClient(create_app()) as client:
        client.cookies.set("theme", "dark")
        created = client.post("/api/orgs", json={"name": "Local Team"})
        plugin_install = client.post(
            "/api/plugins/install",
            json={"manifest": {}, "sourceType": "local", "sourceLocator": "x"},
        )
        llm_write = client.post("/api/llm/providers", json={"id": "unsafe"})
        browser_session = client.get("/api/auth/get-session")

    assert created.status_code == 503
    assert plugin_install.status_code == 503
    assert llm_write.status_code == 503
    assert browser_session.json() is None


def test_session_user_can_access_only_active_membership_organizations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "session-membership.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("OCTOPUS_AUTO_MIGRATE", "1")
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED", "0")

    from server.app import create_app

    with TestClient(create_app()) as client:
        owner = client.post(
            "/api/auth/sign-up/email",
            json={
                "name": "Owner",
                "email": "owner@example.com",
                "password": "secure-password",
            },
        )
        member_org = client.post(
            "/api/orgs",
            json={"name": "Member Team"},
            headers={"origin": "http://testserver"},
        ).json()
        other_org = client.post(
            "/api/orgs",
            json={"name": "Other Team"},
            headers={"origin": "http://testserver"},
        ).json()
        invite = client.post(
            f"/api/orgs/{member_org['id']}/invites",
            json={"allowedJoinTypes": "human"},
            headers={"origin": "http://testserver"},
        ).json()
        signed_out = client.post(
            "/api/auth/sign-out", headers={"origin": "http://testserver"}
        )
        registered = client.post(
            "/api/auth/sign-up/email",
            json={
                "name": "Member",
                "email": "member@example.com",
                "password": "secure-password",
            },
        )
        accepted = client.post(
            f"/api/invites/{invite['token']}/accept",
            headers={"origin": "http://testserver"},
        )
        own_org = client.get(f"/api/orgs/{member_org['id']}/resources")
        forbidden_org = client.get(f"/api/orgs/{other_org['id']}/resources")
        forbidden_runtime_write = client.post(
            f"/api/orgs/{member_org['id']}/runtime-providers",
            json={"runtimeType": "codex_local", "providerId": "forbidden"},
            headers={"origin": "http://testserver"},
        )
        forbidden_resource_write = client.post(
            f"/api/orgs/{member_org['id']}/resources",
            json={"name": "forbidden"},
            headers={"origin": "http://testserver"},
        )
        forbidden_cost_write = client.post(
            f"/api/orgs/{member_org['id']}/cost-events",
            json={"costCents": 999, "sourceType": "forged"},
            headers={"origin": "http://testserver"},
        )
        visible_orgs = client.get("/api/orgs")

    assert owner.status_code == 201
    assert signed_out.status_code == 200
    assert registered.status_code == 201
    assert accepted.status_code == 200
    assert own_org.status_code == 200
    assert forbidden_org.status_code == 403
    assert forbidden_runtime_write.status_code == 403
    assert forbidden_resource_write.status_code == 403
    assert forbidden_cost_write.status_code == 403
    assert visible_orgs.status_code == 200
    assert [org["id"] for org in visible_orgs.json()] == [member_org["id"]]


def test_new_session_user_cannot_see_existing_organization_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "new-user-isolation.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("OCTOPUS_AUTO_MIGRATE", "1")
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED", "0")

    from server.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1:8000") as client:
        user_a = client.post(
            "/api/auth/sign-up/email",
            json={
                "name": "User A",
                "email": "user-a@example.com",
                "password": "secure-password",
            },
        )
        existing_org = client.post(
            "/api/orgs",
            json={"name": "User A Team"},
            headers={"origin": "http://127.0.0.1:8000"},
        ).json()
        signed_out = client.post(
            "/api/auth/sign-out", headers={"origin": "http://127.0.0.1:8000"}
        )
        registered = client.post(
            "/api/auth/sign-up/email",
            json={
                "name": "User B",
                "email": "user-b@example.com",
                "password": "secure-password",
            },
        )
        visible_orgs = client.get("/api/orgs")
        forbidden_resources = client.get(f"/api/orgs/{existing_org['id']}/resources")
        forbidden_issues = client.get(f"/api/orgs/{existing_org['id']}/issues")
        forbidden_agents = client.get(f"/api/orgs/{existing_org['id']}/agents")
        own_org = client.post(
            "/api/orgs",
            json={"name": "User B Team"},
            headers={"origin": "http://127.0.0.1:5175"},
        )
        rejected_cross_site_create = client.post(
            "/api/orgs",
            json={"name": "Untrusted Team"},
            headers={"origin": "https://untrusted.example"},
        )
        visible_after_create = client.get("/api/orgs")
        own_org_detail = client.get(f"/api/orgs/{own_org.json()['id']}")
        own_agent_name = client.get(
            f"/api/orgs/{own_org.json()['id']}/agents/name-suggestion"
        )
        own_agent = client.post(
            f"/api/orgs/{own_org.json()['id']}/agent-hires",
            json={"name": "User B Agent", "role": "engineer"},
            headers={"origin": "http://127.0.0.1:5175"},
        )
        own_agent_skills = client.get(
            f"/api/agents/{own_agent.json()['agent']['id']}/skills"
        )
        own_agent_configuration = client.get(
            f"/api/agents/{own_agent.json()['agent']['id']}/configuration"
        )
        own_agent_config_revisions = client.get(
            f"/api/agents/{own_agent.json()['agent']['id']}/config-revisions"
        )
        own_agent_runtime_state = client.get(
            f"/api/agents/{own_agent.json()['agent']['id']}/runtime-state"
        )
        own_agent_task_sessions = client.get(
            f"/api/agents/{own_agent.json()['agent']['id']}/task-sessions"
        )
        own_agent_skills_sync = client.post(
            f"/api/agents/{own_agent.json()['agent']['id']}/skills/sync",
            json={"desiredSkills": []},
            headers={"origin": "http://127.0.0.1:5175"},
        )
        approved_hire = client.post(
            f"/api/approvals/{own_agent.json()['approval']['id']}/approve",
            json={},
            headers={"origin": "http://127.0.0.1:5175"},
        )

    assert user_a.status_code == 201
    assert signed_out.status_code == 200
    assert registered.status_code == 201
    assert visible_orgs.status_code == 200
    assert visible_orgs.json() == []
    assert forbidden_resources.status_code == 403
    assert forbidden_issues.status_code == 403
    assert forbidden_agents.status_code == 403
    assert own_org.status_code == 200
    assert rejected_cross_site_create.status_code == 403
    assert [org["id"] for org in visible_after_create.json()] == [own_org.json()["id"]]
    assert own_org_detail.status_code == 200
    assert own_agent_name.status_code == 200
    assert own_agent.status_code == 201
    assert own_agent_skills.status_code == 200
    assert own_agent_configuration.status_code == 200
    assert own_agent_config_revisions.status_code == 200
    assert own_agent_runtime_state.status_code == 200
    assert own_agent_task_sessions.status_code == 200
    assert own_agent_skills_sync.status_code == 200
    assert approved_hire.status_code == 200


async def test_local_password_and_session_authenticate_user(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            user_id, token = await LocalPasswordAuth(session).register(
                name="Alice", email="Alice@example.com", password="secure-password"
            )
            result = await SessionAuth(session).authenticate(token)
            assert result is not None
            assert result.principal == PrincipalRef(type="user", id=user_id)
            assert result.source == "session"
            signed_in_user_id, second_token = await LocalPasswordAuth(session).sign_in(
                email="alice@example.com", password="secure-password"
            )
            assert signed_in_user_id == user_id
            assert second_token != token


async def test_proxy_token_requires_identity_and_active_role(
    session_factory: async_sessionmaker,
) -> None:
    secret = "proxy-secret"
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, "proxy")
            await _seed_user(session, "user-proxy", "proxy@example.com")
            await RoleService(session).ensure(
                "organization",
                org_id,
                PrincipalRef(type="user", id="user-proxy"),
                role="member",
            )
            await ensure_external_identity(
                session,
                issuer="https://epaichat.example",
                subject="external-1",
                user_id="user-proxy",
            )
            token = _jwt(
                secret,
                {
                    "iss": "https://epaichat.example",
                    "aud": "octopus",
                    "sub": "external-1",
                    "iat": int(time.time()),
                    "exp": int(time.time()) + 300,
                    "jti": "token-1",
                    "org_id": org_id,
                },
            )
            result = await ProxyTokenAuth(
                session,
                secret=secret,
                issuer="https://epaichat.example",
                audience="octopus",
            ).authenticate(f"Bearer {token}")
            assert result is not None
            assert result.principal.id == "user-proxy"
            assert result.org_id == org_id


async def test_proxy_scoped_actor_cannot_resolve_another_organization(
    session_factory: async_sessionmaker,
) -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    request.state.actor = {
        "type": "user",
        "id": "user-proxy",
        "userId": "user-proxy",
        "orgId": "org-from-token",
        "source": "proxy_token",
    }
    async with session_factory() as session:
        with pytest.raises(HTTPException) as error:
            await get_identity_context(request, orgId="another-org", session=session)
    assert error.value.status_code == 403


async def test_human_invite_acceptance_is_idempotent_and_adds_member(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, "invite")
            await _seed_user(session, "invitee", "invitee@example.com")
            invitations = InvitationService(session)
            invite, token = await invitations.create(
                org_id,
                allowed_join_types="human",
                defaults_payload=None,
                invited_by_user_id=None,
            )
            accepted = await invitations.accept_human(token, "invitee")
            replayed = await invitations.accept_human(token, "invitee")
            role = await RoleService(session).get(
                "organization", org_id, PrincipalRef(type="user", id="invitee")
            )
            assert accepted.id == invite.id == replayed.id
            assert role is not None
            assert role.status == "active"


async def test_role_management_replaces_permissions_through_service_boundary(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, "permissions")
            await _seed_user(session, "member", "member@example.com")
            role = await RoleService(session).ensure(
                "organization",
                org_id,
                PrincipalRef(type="user", id="member"),
                role="member",
            )
            updated = await RoleManagementService(session).replace_permissions(
                org_id,
                role.id,
                [PermissionSpec(permission="users:invite")],
                granted_by_user_id=None,
            )
            context = await IdentityContextResolver(session).resolve(
                actor_type="user", actor_id="member", org_id=org_id, source="test"
            )
            assert updated is not None
            assert context.permissions == frozenset({"users:invite"})


async def _seed_org(session: AsyncSession, key: str) -> str:
    org_id = str(uuid5(NAMESPACE_URL, f"octopus-auth:{key}"))
    await create_organization(
        session,
        id=org_id,
        url_key=f"auth-{key}",
        name=f"Auth {key}",
        issue_prefix=key[:6].upper(),
    )
    return org_id


async def _seed_user(session: AsyncSession, user_id: str, email: str) -> None:
    now = datetime.now(UTC)
    await ensure_user(
        session,
        {
            "id": user_id,
            "name": user_id,
            "email": email,
            "email_verified": True,
            "created_at": now,
            "updated_at": now,
        },
    )


def _jwt(secret: str, claims: dict[str, object]) -> str:
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(claims)
    signature = hmac.new(
        secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
    ).digest()
    return (
        f"{header}.{payload}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    )


def _encode(value: dict[str, object]) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
