from __future__ import annotations

from fastapi import FastAPI

from .orgs import router as orgs_router


def register_routes(app: FastAPI) -> None:
    app.include_router(orgs_router)
