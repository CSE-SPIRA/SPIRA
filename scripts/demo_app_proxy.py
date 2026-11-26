"""Forward local web and Android App requests with server-side credentials."""

import os
import re

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware


def create_app():
    server = os.environ["SPIRA_SERVER_URL"]
    household = os.environ["SPIRA_HOUSEHOLD"]
    origin = os.getenv("SPIRA_WEB_ORIGIN")
    phone_token = os.getenv("SPIRA_PHONE_TOKEN")
    first_run = os.getenv("SPIRA_DEMO_FIRST_RUN") == "1"
    app_key = f"Bearer {os.environ['SPIRA_APP_TOKEN']}"
    household_id = r"h_[a-z0-9]+" if first_run else re.escape(household)
    household_path = rf"/v1/households/{household_id}"
    patterns = {
        "GET": rf"/v1/episodes/ep_[a-z0-9]+(?:/rationale)?|{household_path}/(?:episodes|cards|memory)",
        "PUT": rf"/v1/episodes/ep_[a-z0-9]+/order|{household_path}/(?:profile|calendar)",
        "DELETE": rf"{household_path}/memory/(?:syn_[a-zA-Z0-9_-]+|home_{household_id}_ep_[a-z0-9]+_[0-9]+)",
        "POST": rf"/v1/orders|/v1/cards/nc_[a-z0-9]+/reactions|{household_path}/pause",
    }
    if first_run:
        patterns["POST"] += "|/v1/households"
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=[origin] if origin else [], allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type"])

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def forward(request: Request):
        request_origin = request.headers.get("origin")
        web = origin and request_origin == origin
        phone = (phone_token and request_origin is None
                 and request.headers.get("authorization") == f"Bearer {phone_token}")
        if not (web or phone):
            raise HTTPException(403)
        method, path = request.method, request.url.path
        headers = {"Accept": "application/json"}
        if re.fullmatch(patterns[method], path):
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
