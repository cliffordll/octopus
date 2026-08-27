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
from packages.database.queries.external_user_bindings import (
    ensure_external_user_binding,
)
from packages.database.queries.organizations import create_organization
from packages.database.queries.users import ensure_user
from packages.database.schema import Base
from server.access import PermissionGrantSpec
from server.auth import LocalPasswordAuth, PasswordHasher, ProxyTokenAuth, SessionAuth
from server.identity import IdentityContextResolver, PrincipalRef
from server.dependencies.identity import get_identity_context
from server.invitations import InvitationService
from server.membership import MemberService
from server.membership.management import MemberManagementService


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


def test_human_auth_tables_match_upstream_contract() -> None:
    assert {
        "session",
        "account",
        "verification",
        "external_user_bindings",
        "invites",
    }.issubset(Base.metadata.tables)
    assert {"expires_at", "token", "user_id"}.issubset(
        Base.metadata.tables["session"].columns.keys()
    )
    assert {"account_id", "provider_id", "password"}.issubset(
        Base.metadata.tables["account"].columns.keys()
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


def test_local_owner_can_manage_members_and_invites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "member-management.db"
    monkeypatch.setenv("OCTOPUS_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("OCTOPUS_AUTO_MIGRATE", "1")
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED", "0")

    from server.app import create_app

    with TestClient(create_app()) as client:
        organization = client.post("/api/orgs", json={"name": "Team"}).json()
        org_id = organization["id"]
        members = client.get(f"/api/orgs/{org_id}/members")
        created = client.post(
            f"/api/orgs/{org_id}/invites",
            json={"allowedJoinTypes": "human"},
        )
        inspected = client.get(f"/api/invites/{created.json()['token']}")

    assert members.status_code == 200
    assert members.json()[0]["principalId"] == "local-board"
    assert created.status_code == 201
    assert inspected.status_code == 200
    assert inspected.json()["allowedJoinTypes"] == "human"


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


async def test_proxy_token_requires_binding_and_active_membership(
    session_factory: async_sessionmaker,
) -> None:
    secret = "proxy-secret"
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, "proxy")
            await _seed_user(session, "user-proxy", "proxy@example.com")
            await MemberService(session).ensure(
                org_id, PrincipalRef(type="user", id="user-proxy")
            )
            await ensure_external_user_binding(
                session,
                issuer="https://epaichat.example",
                subject="external-1",
                local_user_id="user-proxy",
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
            membership = await MemberService(session).get(
                org_id, PrincipalRef(type="user", id="invitee")
            )
            assert accepted.id == invite.id == replayed.id
            assert membership is not None
            assert membership.status == "active"


async def test_member_management_replaces_grants_through_service_boundary(
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        async with async_write_transaction(session):
            org_id = await _seed_org(session, "permissions")
            await _seed_user(session, "member", "member@example.com")
            member = await MemberService(session).ensure(
                org_id, PrincipalRef(type="user", id="member")
            )
            updated = await MemberManagementService(session).replace_permissions(
                org_id,
                member.id,
                [PermissionGrantSpec(permission="users:invite")],
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
