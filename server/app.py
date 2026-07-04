from __future__ import annotations

from fastapi import FastAPI

from .app_logging import install_sqlalchemy_pool_cancel_filter
from .config import load_settings
from .lifespan import lifespan
from .middleware import ActorContextMiddleware
from .routes import register_routes


def create_app() -> FastAPI:
    install_sqlalchemy_pool_cancel_filter()
    settings = load_settings()
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(ActorContextMiddleware)
    register_routes(app)
    return app


app = create_app()
