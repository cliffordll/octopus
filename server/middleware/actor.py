from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from packages.database.clients import async_write_transaction
from server.auth import (
    ProxyTokenAuth,
    RunTokenAuth,
    SessionAuth,
    is_trusted_session_origin,
)
from starlette.responses import JSONResponse
from server.identity.actor_context import AuthenticatedActorProjector


class ActorContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        settings = request.app.state.settings
        _set_actor_context(request, settings)
        if not hasattr(request.state, "actor"):
            await _resolve_authenticated_actor(request, settings)
        if not _session_csrf_allowed(request):
            await JSONResponse(
                {"detail": "Session request origin is not trusted"},
                status_code=403,
            )(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _set_actor_context(request: Request, settings: object) -> None:
    if not hasattr(request.state, "actor") and getattr(
        settings, "local_trusted", False
    ):
        test_agent_id = request.headers.get("x-test-agent-id")
        test_org_id = request.headers.get("x-test-org-id")
        run_id = request.headers.get("x-test-run-id") or request.headers.get(
            "x-octopus-run-id"
        )
        if test_agent_id and test_org_id:
            request.state.actor = {
                "type": "agent",
                "id": test_agent_id,
                "agentId": test_agent_id,
                "orgId": test_org_id,
                "runId": run_id,
                "source": "local_test_header",
            }


async def actor_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[object]]
) -> object:
    settings = request.app.state.settings
    _set_actor_context(request, settings)
    if not hasattr(request.state, "actor"):
        await _resolve_authenticated_actor(request, settings)
    if not _session_csrf_allowed(request):
        return JSONResponse(
            {"detail": "Session request origin is not trusted"}, status_code=403
        )
    return await call_next(request)


async def _resolve_authenticated_actor(request: Request, settings: object) -> None:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        return
    cookie_name = getattr(settings, "auth_session_cookie_name", "octopus_session")
    cookie = request.cookies.get(cookie_name)
    secret = getattr(settings, "proxy_auth_secret", None)
    issuer = getattr(settings, "proxy_auth_issuer", None)
    audience = getattr(settings, "proxy_auth_audience", None)
    authorization = request.headers.get("authorization")
    has_bearer_credential = bool(authorization)
    if not cookie and not has_bearer_credential:
        return
    async with session_factory() as session:
        async with async_write_transaction(session):
            result = await SessionAuth(session).authenticate(cookie) if cookie else None
            if result is None and authorization:
                result = await RunTokenAuth(session).authenticate(authorization)
            if result is None and authorization:
                if secret and issuer and audience:
                    result = await ProxyTokenAuth(
                        session,
                        secret=str(secret),
                        issuer=str(issuer),
                        audience=str(audience),
                    ).authenticate(str(authorization))
            if result is not None:
                request.state.actor = await AuthenticatedActorProjector(
                    session
                ).project(result)


def _session_csrf_allowed(request: Request) -> bool:
    actor = getattr(request.state, "actor", None)
    if not isinstance(actor, dict) or actor.get("source") != "session":
        return True
    return is_trusted_session_origin(
        method=request.method,
        origin=request.headers.get("origin"),
        request_url=str(request.url),
        allow_loopback_proxy=bool(
            getattr(request.app.state.settings, "local_trusted", False)
        ),
    )
