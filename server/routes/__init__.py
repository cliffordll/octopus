from __future__ import annotations

from fastapi import FastAPI

from .agents import router as agents_router
from .approvals import router as approvals_router
from .assets import router as assets_router
from .health import router as health_router
from .issues import router as issues_router
from .messenger import router as messenger_router
from .organization_skills import router as organization_skills_router
from .orgs import router as orgs_router
from .projects import router as projects_router
from .run_intelligence import router as run_intelligence_router
from .runtime_providers import router as runtime_providers_router
from .chats import router as chats_router
from .goals import router as goals_router
from .workspace_operations import router as workspace_operations_router


def register_routes(app: FastAPI) -> None:
    app.include_router(health_router)
    app.include_router(orgs_router)
    app.include_router(organization_skills_router)
    app.include_router(assets_router)
    app.include_router(issues_router)
    app.include_router(approvals_router)
    app.include_router(projects_router)
    app.include_router(runtime_providers_router)
    app.include_router(agents_router)
    app.include_router(workspace_operations_router)
    app.include_router(run_intelligence_router)
    app.include_router(chats_router)
    app.include_router(messenger_router)
    app.include_router(goals_router)
