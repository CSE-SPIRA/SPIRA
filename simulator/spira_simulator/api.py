"""HTTP boundary for the independent World walking skeleton."""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .storage import InvalidMutation, WorldStorage


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str = Field(min_length=1)
    values: dict[str, bool]
    provenance: str = "unknown"


VIEWER = """<!doctype html><html><head><meta charset='utf-8'>
<title>SPIRA Simulator</title></head><body><h1>Independent virtual world</h1>
<pre id='world'>Loading…</pre><script>
fetch('/sim/snapshot').then(r => r.json()).then(v => {
  document.getElementById('world').textContent = JSON.stringify(v, null, 2);
});
</script></body></html>"""


def create_app(db_path: Path | None = None, operator_enabled: bool | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        path = db_path or Path(os.environ.get("WORLD_DB", "world.db"))
        app.state.world = WorldStorage(path)
        app.state.operator_enabled = operator_enabled if operator_enabled is not None else (
            os.environ.get("WORLD_OPERATOR", "0") == "1"
        )
        try:
            yield
        finally:
            app.state.world.close()

    application = FastAPI(title="SPIRA Simulator walking skeleton", lifespan=lifespan)

    @application.get("/health")
    async def health(request: Request):
        return {
            "status": "ready",
            "role": "simulator",
            "world_revision": request.app.state.world.revision,
            "physical": False,
        }

    @application.get("/sim/snapshot")
    async def snapshot(request: Request):
        return request.app.state.world.snapshot()

    @application.get("/sim/journal")
    async def journal(
        request: Request,
        after: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ):
        return request.app.state.world.journal(after, limit)

    @application.get("/sim/viewer", response_class=HTMLResponse)
    async def viewer():
        return VIEWER

    @application.post("/operator/mutate")
    async def mutate(body: Mutation, request: Request):
        if not request.app.state.operator_enabled:
            raise HTTPException(404, "operator disabled")
        try:
            return request.app.state.world.mutate(
                body.target, body.values, body.provenance, time.time()
            )
        except InvalidMutation as exc:
            raise HTTPException(400, str(exc)) from exc

    return application


app = create_app()
