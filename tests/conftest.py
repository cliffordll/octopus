from __future__ import annotations

import shutil
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest


_LEGACY_TEST_ROOT_ID = "legacy-contract-root"


@pytest.fixture(autouse=True)
def isolate_octopus_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    octopus_home = tmp_path / "octopus-home"
    monkeypatch.setenv("OCTOPUS_HOME", str(octopus_home))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "test")
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "0")
    try:
        yield
    finally:
        shutil.rmtree(octopus_home, ignore_errors=True)


@pytest.fixture(autouse=True)
def legacy_contract_root_actor(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep pre-access HTTP contracts focused on their original behavior.

    Step 30 access tests exercise real sessions, roles, and permissions. Older
    route contracts predate authentication and use local trusted mode only to
    obtain a human caller. Give those tests an explicit test-only Root identity
    without restoring the removed production ``local-board`` bypass.
    """
    if getattr(request.module, "USE_REAL_ACCESS", False):
        return

    from server.identity import IdentityContext, PrincipalRef
    from server.identity.resolver import IdentityContextResolver
    from server.middleware import actor as actor_middleware
    from packages.database.schema import Agent
    from packages.shared.constants.access import PERMISSION_KEYS

    original_set_actor_context = actor_middleware._set_actor_context
    original_resolve = IdentityContextResolver.resolve

    def set_actor_context(http_request: Any, settings: object) -> None:
        if http_request.headers.get("x-test-actor-type") == "board":
            actor_id = http_request.headers.get("x-test-actor-id", "test-actor")
            http_request.state.actor = {
                "type": "user",
                "id": actor_id,
                "userId": actor_id,
                "isRoot": True,
                "source": "legacy_contract_root",
            }
            return
        original_set_actor_context(http_request, settings)
        if hasattr(http_request.state, "actor"):
            return
        if not getattr(settings, "local_trusted", False):
            return
        if any(
            http_request.headers.get(name)
            for name in (
                "x-test-actor-type",
                "x-test-agent-id",
                "x-test-user-id",
            )
        ):
            return
        http_request.state.actor = {
            "type": "user",
            "id": _LEGACY_TEST_ROOT_ID,
            "userId": _LEGACY_TEST_ROOT_ID,
            "isRoot": True,
            "source": "legacy_contract_root",
        }

    async def resolve_identity(
        self: IdentityContextResolver,
        *,
        actor_type: str,
        actor_id: str,
        org_id: str | None,
        source: str,
        run_id: str | None = None,
    ) -> IdentityContext:
        if (
            actor_type == "board"
            or actor_id == _LEGACY_TEST_ROOT_ID
            or source == "legacy_contract_root"
        ):
            return IdentityContext(
                principal=PrincipalRef(type="user", id=actor_id),
                org_id=org_id,
                source=source,
                run_id=run_id,
                is_root=True,
            )
        if actor_type == "agent" and org_id is not None:
            resolved = await original_resolve(
                self,
                actor_type=actor_type,
                actor_id=actor_id,
                org_id=org_id,
                source=source,
                run_id=run_id,
            )
            if resolved.has_active_role:
                return resolved
            agent = await self._session.get(Agent, actor_id)
            if agent is not None and agent.org_id == org_id:
                return IdentityContext(
                    principal=PrincipalRef(type="agent", id=actor_id),
                    org_id=org_id,
                    role_id=f"legacy-agent-role:{actor_id}",
                    role="member",
                    permissions=frozenset(
                        PERMISSION_KEYS if agent.role == "ceo" else ("tasks:assign",)
                    ),
                    source=source,
                    run_id=run_id,
                )
        return await original_resolve(
            self,
            actor_type=actor_type,
            actor_id=actor_id,
            org_id=org_id,
            source=source,
            run_id=run_id,
        )

    monkeypatch.setattr(actor_middleware, "_set_actor_context", set_actor_context)
    monkeypatch.setattr(IdentityContextResolver, "resolve", resolve_identity)
