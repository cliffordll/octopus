from __future__ import annotations

from fastapi import FastAPI

from .approvals import router as approvals_router
from .issues import router as issues_router
from .orgs import router as orgs_router


def register_routes(app: FastAPI) -> None:
    app.include_router(orgs_router)
    app.include_router(issues_router)
    app.include_router(approvals_router)
