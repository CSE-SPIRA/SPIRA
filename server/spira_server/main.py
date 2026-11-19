"""App factory (spec §2.1): settings, DB, routers, scheduler start/stop, /health."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .api import errors
from .db.engine import db_ready
from .kb import embedding
from .settings import get_settings

log = logging.getLogger(__name__)

# Startup / shutdown hooks registered by later modules (scheduler, routers). Kept as lists so tests can run the app
# without background jobs.
on_start: list[Callable[[FastAPI], None]] = []
on_stop: list[Callable[[FastAPI], None]] = []


def create_app(*, start_background: bool = True) -> FastAPI:
    get_settings()  # fail fast on missing variables

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        embedding.warm_up_in_background()
        if start_background:
            for hook in on_start:
                hook(app)
        yield
        if start_background:
            for hook in on_stop:
                hook(app)

    app = FastAPI(title="SPIRA Server", version="0.1.0", lifespan=lifespan)
    errors.install(app)

    @app.get("/health")
    def health() -> JSONResponse:
        db, emb = db_ready(), embedding.ready()
        if db and emb:
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "degraded", "db": db, "embedding": emb}, status_code=503)

    return app


def __getattr__(name: str):  # `uvicorn spira_server.main:app`
    if name == "app":
        return create_app()
    raise AttributeError(name)
