from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.users import get_user_by_id
from packages.shared.api_paths.access import (
    AUTH_SESSION_PATH,
    AUTH_SIGN_IN_PATH,
    AUTH_SIGN_OUT_PATH,
    AUTH_SIGN_UP_PATH,
)
from packages.shared.validators.access import validate_email_auth
from server.auth import LocalPasswordAuth, SessionAuth
from server.dependencies.database import get_session

router = APIRouter(tags=["auth"])


@router.post(AUTH_SIGN_UP_PATH, status_code=status.HTTP_201_CREATED)
async def sign_up(
    request: Request,
    response: Response,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        payload = validate_email_auth(body, require_name=True)
        user_id, token = await LocalPasswordAuth(session).register(
            name=payload["name"],
            email=payload["email"],
            password=payload["password"],
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _set_session_cookie(request, response, token)
    return {"user": {"id": user_id, "name": payload["name"], "email": payload["email"]}}


@router.post(AUTH_SIGN_IN_PATH)
async def sign_in(
    request: Request,
    response: Response,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        payload = validate_email_auth(body, require_name=False)
        user_id, token = await LocalPasswordAuth(session).sign_in(
            email=payload["email"],
            password=payload["password"],
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_session_cookie(request, response, token)
    return {"user": {"id": user_id, "email": payload["email"]}}


@router.get(AUTH_SESSION_PATH)
async def get_auth_session(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | None:
    actor = getattr(request.state, "actor", None)
    user_id = actor.get("userId") if isinstance(actor, dict) else None
    if not user_id:
        return None
    user = await get_user_by_id(session, str(user_id))
    source = actor.get("source") if isinstance(actor, dict) else None
    return (
        {
            "user": {"id": user.id, "name": user.name, "email": user.email},
            "session": {"source": source},
        }
        if user
        else None
    )


@router.post(AUTH_SIGN_OUT_PATH)
async def sign_out(
    request: Request, response: Response, session: AsyncSession = Depends(get_session)
) -> dict[str, bool]:
    cookie_name = request.app.state.settings.auth_session_cookie_name
    token = request.cookies.get(cookie_name)
    if token:
        await SessionAuth(session).revoke(token)
    response.delete_cookie(cookie_name, path="/")
    return {"success": True}


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        request.app.state.settings.auth_session_cookie_name,
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
        path="/",
    )
