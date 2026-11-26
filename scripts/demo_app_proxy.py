"""Forward the local App preview's requests with server-side credentials."""

import os
import re

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware


def create_app():
    server = os.environ["SPIRA_SERVER_URL"]
    household = os.environ["SPIRA_HOUSEHOLD"]
    origin = os.environ["SPIRA_WEB_ORIGIN"]
    app_key = f"Bearer {os.environ['SPIRA_APP_TOKEN']}"
    household_path = f"/v1/households/{household}"
    routes = {
        ("POST", "/v1/orders"), ("GET", f"{household_path}/episodes"),
        ("GET", f"{household_path}/cards"), ("GET", f"{household_path}/memory"),
        ("PUT", f"{household_path}/profile"), ("PUT", f"{household_path}/calendar"),
        ("POST", f"{household_path}/pause"),
    }
    patterns = {
        "GET": r"/v1/episodes/ep_[a-z0-9]+(?:/rationale)?",
        "PUT": r"/v1/episodes/ep_[a-z0-9]+/order",
        "DELETE": rf"{household_path}/memory/(?:syn_[a-zA-Z0-9_-]+|home_{household}_ep_[a-z0-9]+_[0-9]+)",
        "POST": r"/v1/cards/nc_[a-z0-9]+/reactions",
    }
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[origin], allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def forward(request: Request):
        if request.headers.get("origin") != origin:
            raise HTTPException(403)
        method, path = request.method, request.url.path
        headers = {"Accept": "application/json"}
        if (method, path) in routes or re.fullmatch(patterns.get(method, r"(?!)"), path):
            headers["Authorization"] = app_key
        elif (method, path) != ("GET", "/health"):
            raise HTTPException(404)
        if content_type := request.headers.get("content-type"):
            headers["Content-Type"] = content_type
        try:
            async with httpx.AsyncClient(timeout=35, trust_env=False) as client:
                upstream = await client.request(method, f"{server}{path}", headers=headers,
                                                params=request.query_params, content=await request.body())
        except httpx.HTTPError as error:
            raise HTTPException(502, "Peer is unavailable") from error
        return Response(upstream.content, status_code=upstream.status_code, headers={
            name: upstream.headers[name] for name in ("content-type",) if name in upstream.headers
        } | {"Cache-Control": "no-store"})

    return app
