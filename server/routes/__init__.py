from __future__ import annotations

from fastapi import FastAPI

from .agents import router as agents_router
from .approvals import router as approvals_router
from .issues import router as issues_router
from .messenger import router as messenger_router
from .organization_skills import router as organization_skills_router
from .orgs import router as orgs_router
from .projects import router as projects_router
from .chats import router as chats_router
from .goals import router as goals_router


def register_routes(app: FastAPI) -> None:
    app.include_router(orgs_router)
    app.include_router(organization_skills_router)
    app.include_router(issues_router)
    app.include_router(approvals_router)
    app.include_router(projects_router)
    app.include_router(agents_router)
    app.include_router(chats_router)
    app.include_router(messenger_router)
    app.include_router(goals_router)
