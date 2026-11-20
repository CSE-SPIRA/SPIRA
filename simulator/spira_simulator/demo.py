"""Two-page demo shell: the Server's reasoning, then the house.

The pages read only the team contract (episode, rationale, cards) through a
small allow-listed proxy, the World snapshot, and the Hub's read-only state.
Nothing here decides what the house does.
"""

import asyncio
import os
import re
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

DEMO_UI = Path(__file__).with_name("ui") / "demo"
ASSET = re.compile(r"^[a-z0-9_.\-]+\.(?:html|css|js|json|svg|png|jpg|woff2)$")
MEDIA = {
    ".html": "text/html", ".css": "text/css", ".js": "text/javascript",
    ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
    ".jpg": "image/jpeg", ".woff2": "font/woff2",
}
# Read-only contract routes the reasoning page may use.
SERVER_READS = (
    re.compile(r"^v1/episodes/ep_[A-Za-z0-9_]+$"),
    re.compile(r"^v1/episodes/ep_[A-Za-z0-9_]+/rationale$"),
    re.compile(r"^v1/households/h_[A-Za-z0-9_]+/cards$"),
)
SAMPLE_EPISODES = {"birthday": "ep_9031", "groceries": "ep_9150"}


def demo_config():
    return {
        "server": (os.getenv("DEMO_SERVER_URL") or "").rstrip("/"),
        "token": os.getenv("DEMO_APP_TOKEN") or "",
        "hub": (os.getenv("DEMO_HUB_URL") or "").rstrip("/"),
        "fixture_episode": os.getenv("DEMO_FIXTURE_EPISODE") or "",
    }


def same_origin(request: Request):
    origin = request.headers.get("origin")
    if origin is not None and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Use the demo page")


def mount_demo(application: FastAPI, apply_home_event):
    fixture_share = asyncio.Lock()

    @application.get("/demo")
    def demo_page():
        return FileResponse(DEMO_UI / "index.html", media_type="text/html")

    @application.get("/demo/assets/{name}")
    def demo_asset(name: str):
        path = DEMO_UI / name
        if not ASSET.match(name) or not path.is_file():
            raise HTTPException(404, "No such demo asset")
        return FileResponse(path, media_type=MEDIA[path.suffix])

    @application.get("/demo/api/config")
    def config(request: Request):
        cfg = demo_config()
        return {
            "household_id": request.app.state.world.profile.household_id,
            "server": bool(cfg["server"]),
            "hub": bool(cfg["hub"]),
            "fixture": bool(cfg["fixture_episode"]),
        }

    @application.get("/demo/api/server/{path:path}")
    async def server_read(path: str, request: Request):
        cfg = demo_config()
        if not cfg["server"]:
            raise HTTPException(503, "DEMO_SERVER_URL is not set")
        if not any(rule.match(path) for rule in SERVER_READS):
            raise HTTPException(404, "Not a demo read")
        async with httpx.AsyncClient(timeout=10) as client:
            upstream = await client.get(
                f"{cfg['server']}/{path}",
                params=dict(request.query_params),
                headers={"Authorization": f"Bearer {cfg['token']}"},
            )
        return JSONResponse(upstream.json(), status_code=upstream.status_code)

    @application.post("/demo/api/order")
    async def share_order(
        request: Request,
        images: list[UploadFile],
        sample: Literal["birthday", "groceries"] | None = Form(default=None),
    ):
        """Stand-in for the phone's share: send the screenshots as the App would."""
        same_origin(request)
        cfg = demo_config()
        if not cfg["server"]:
            raise HTTPException(503, "DEMO_SERVER_URL is not set")
        if not 1 <= len(images) <= 3:
            raise HTTPException(400, "One to three screenshots")
        household = request.app.state.world.profile.household_id
        auth = {"Authorization": f"Bearer {cfg['token']}"}
        files = [
            ("images", (image.filename or "order.png", await image.read(),
                        image.content_type or "image/png"))
            for image in images
        ]
        async with httpx.AsyncClient(timeout=30) as client:
            async def upload():
                return await client.post(
                    f"{cfg['server']}/v1/orders", headers=auth,
                    data={"household_id": household}, files=files,
                )

            if cfg["fixture_episode"]:
                # The fixture holds a single selection for the next upload.
                async with fixture_share:
                    selection = await client.post(
                        f"{cfg['server']}/_fixture/scene/next-order", headers=auth,
                        json={"episode_id": SAMPLE_EPISODES[sample] if sample else cfg["fixture_episode"],
                              "starts_in_seconds": int(os.getenv("DEMO_STARTS_IN") or "90")},
                    )
                    if sample and not selection.is_success:
                        raise HTTPException(502, "Could not select the fixture order")
                    upstream = await upload()
            else:
                upstream = await upload()
        return JSONResponse(upstream.json(), status_code=upstream.status_code)

    @application.get("/demo/api/hub")
    async def hub_state():
        cfg = demo_config()
        if not cfg["hub"]:
            raise HTTPException(503, "DEMO_HUB_URL is not set")
        async with httpx.AsyncClient(timeout=5) as client:
            upstream = await client.get(f"{cfg['hub']}/state")
        body = upstream.json()
        return {"ledger": body.get("ledger", []), "waiting": body.get("waiting", [])}

    @application.post("/demo/api/home/{action}")
    def home_event(action: str, request: Request):
        """The timeline's world events (package, guests, end): the same as the operator's."""
        same_origin(request)
        if action not in request.app.state.world.profile.home_signals:
            raise HTTPException(404, "No such home event")
        return apply_home_event(request, action)
