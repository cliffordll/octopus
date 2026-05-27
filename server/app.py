from __future__ import annotations

from fastapi import FastAPI

from .config import load_settings
from .lifespan import lifespan
from .middleware import actor_context_middleware
from .routes import register_routes


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.middleware("http")(actor_context_middleware)
    register_routes(app)
    return app


app = create_app()
