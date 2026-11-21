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
import yaml
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from spira_contracts.episode import Episode
from spira_contracts.plan import Action

DEMO_UI = Path(__file__).with_name("ui")
FIXTURES = Path(__file__).resolve().parents[1] / "contracts" / "fixtures"
HOUSE_ASSET = re.compile(r"(?:fonts/)?[a-zA-Z0-9_.-]+\.(?:css|js|svg|jpg|png|woff2|txt)")
# Read-only contract routes the reasoning page may use.
SERVER_READS = (
    re.compile(r"^v1/episodes/ep_[A-Za-z0-9_]+$"),
    re.compile(r"^v1/episodes/ep_[A-Za-z0-9_]+/rationale$"),
    re.compile(r"^v1/households/h_[A-Za-z0-9_]+/cards$"),
)
SAMPLE_EPISODES = {"birthday": "ep_9031", "groceries": "ep_9150"}
HOME_ACTIONS = {"delivery", "guests_arrive", "event_end"}
SIM_READS = {"snapshot": "/sim/snapshot", "viewer": "/sim/viewer?fragment=true"}
COMMAND_PROPERTIES = {"color": "color", "play_mood": "play_mood", "set_cook_standby": "preset"}
STORY_TIMING_KEYS = ("before_start_default_min", "guest_window_before_min", "end_fallback_min")
PACKAGE_EVENT = "package.brought_in"


def demo_config():
    return {
        "server": (os.getenv("DEMO_SERVER_URL") or "").rstrip("/"),
        "token": os.getenv("DEMO_APP_TOKEN") or "",
        "hub": (os.getenv("DEMO_HUB_URL") or "").rstrip("/"),
        "fixture": bool(os.getenv("DEMO_FIXTURE_EPISODE")),
        "household": os.getenv("DEMO_HOUSEHOLD", "h_042"),
    }


def story_timing():
    path = os.getenv("DEMO_NUMBERS_PATH")
    if not path:
        return None
    try:
        numbers = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        timing = {key: {"normal": numbers[key], "demo": numbers["demo"][key]} for key in STORY_TIMING_KEYS}
        quiet = {"normal": numbers.get("quiet_s"), "demo": numbers["demo"].get("quiet_s")}
    except (OSError, ValueError, yaml.YAMLError, KeyError, TypeError):
        return None
    if any(type(value) is not int or value < 0 for pair in timing.values() for value in pair.values()):
        return None
    if all(type(value) is int and value >= 0 for value in quiet.values()):
        timing["quiet_s"] = quiet
    return timing


def fixture_shares():
    """The live fixture rewrites shared_at when replaying a recorded order."""
    shares = {}
    for episode_id in SAMPLE_EPISODES.values():
        try:
            episode = Episode.model_validate_json((FIXTURES / episode_id / "episode.json").read_bytes())
        except (OSError, ValueError):
            continue
        shares[episode.episode_id] = episode.shared_at
    return shares


def same_origin(request: Request):
    origin = request.headers.get("origin")
    if origin is not None and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Use the demo page")


def received_actions(body: dict) -> dict:
    """Project the latest received plans, including actions that have left the waiting list."""
    versions = {row["plan_id"]: row["plan_version"] for row in body.get("ledger", [])
                if row["kind"] == "plan"}
    plans = {plan_id: {} for plan_id in versions}
    for work in body.get("waiting", []):
        plan_id = work["plan_id"]
        if versions.get(plan_id) == work["plan_version"]:
            plans[plan_id][work["task_id"]] = list(work["actions"])

    for story in body.get("task_stories", []):
        plan_id, task_id, steps = story["plan_id"], story["task_id"], story["steps"]
        if plan_id not in plans or not any(
            step["kind"] == "admitted" and step["plan_version"] == versions[plan_id]
            for step in steps
        ):
            continue
        actions = plans[plan_id].setdefault(task_id, [])
        known = {(action["device"], action["cmd"]) for action in actions}
        for step in reversed(steps):
            if step.get("phase") != "run":
                continue
            device, cmd = step["device"], step["cmd"]
            if (device, cmd) in known:
                continue
            desired = step.get("desired") or {}
            value = desired.get(COMMAND_PROPERTIES.get(cmd))
            actions.append(Action(device=device, cmd=cmd, value=value).model_dump(exclude_none=True))
            known.add((device, cmd))
    return plans


def story_ledger(body: dict) -> tuple[list, dict]:
    """Join ledger rows to the Hub's recorded schedule and trigger evidence for display."""
    operations, restores, guest_windows = {}, {}, {}
    package_releases = {
        (version["plan_id"], version["plan_version"])
        for version in body.get("plan_history", [])
        if any(
            change["from"].get("released") is False
            and change["to"].get("event") == PACKAGE_EVENT
            and change["to"].get("released") is True
            for change in (version.get("changes") or {}).get("triggers_changed", [])
        )
    }
    for story in body.get("task_stories", []):
        plan_id, task_id = story["plan_id"], story["task_id"]
        context = {"plan_id": plan_id, "task_id": task_id}
        trigger, triggered, end = {}, {}, {}
        for step in story["steps"]:
            kind = step["kind"]
            if kind == "waiting":
                trigger = step["trigger"]
                if trigger.get("event") == "guest_arrived" and trigger.get("window"):
                    guest_windows.setdefault(plan_id, {})[task_id] = trigger["window"]
            elif kind == "triggered":
                triggered = step
            elif kind == "end":
                end = step
            elif kind == "restore_result":
                restores[step["result_id"]] = end_timing(context, end, step["at"])
            elif operation := step.get("operation_id"):
                if step.get("phase") == "run":
                    how = triggered.get("how")
                    scheduled = trigger.get("time") if how in (None, "unknown") else None
                    if how == "time":
                        scheduled = triggered["at"]
                    operations[operation] = dict(
                        context, scheduled_at=scheduled, anchor="start", observed_at=step["at"],
                        event=triggered.get("event_type", trigger.get("event")),
                    )
                elif step.get("phase") == "restore":
                    operations[operation] = end_timing(context, end, step["at"])

    ledger = []
    for row in body.get("ledger", []):
        timing = operations.get(row.get("operation_id"))
        if row["kind"] == "plan" and (row["plan_id"], row.get("plan_version")) in package_releases:
            timing = {"event": PACKAGE_EVENT}
        elif row["kind"] == "restore" and not timing:
            timing = next((restores[report["id"]] for report in row.get("reports", [])
                           if report["kind"] == "restore" and report["id"] in restores), None)
        ledger.append(dict(row, timing=timing) if timing else row)
    return ledger, guest_windows


def end_timing(context, end, observed_at):
    scheduled = end.get("at") if end.get("rule") in ("time", "or_time") else None
    return dict(context, scheduled_at=scheduled, anchor="end", observed_at=observed_at,
                event=end.get("event_type"))


async def simulator_read(path: str, headers=None):
    simulator = (os.getenv("DEMO_SIMULATOR_URL") or "").rstrip("/")
    if not simulator:
        raise HTTPException(503, "DEMO_SIMULATOR_URL is not set")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            upstream = await client.get(f"{simulator}{path}", headers=headers)
    except httpx.HTTPError as error:
        raise HTTPException(502, "Simulator is unavailable") from error
    return Response(upstream.content, status_code=upstream.status_code, headers={
        name: upstream.headers[name]
        for name in ("content-type", "cache-control", "etag", "last-modified")
        if name in upstream.headers
    })


def create_app():
    application = FastAPI(title="SPIRA demo shell", docs_url=None, redoc_url=None, openapi_url=None)
    fixture_share = asyncio.Lock()
    application.mount("/demo/assets", StaticFiles(directory=DEMO_UI), name="demo-assets")

    @application.get("/demo")
    def demo_page():
        return FileResponse(DEMO_UI / "index.html", media_type="text/html")

    @application.get("/sim/assets/house/{asset:path}")
    async def house_asset(asset: str, request: Request):
        if not HOUSE_ASSET.fullmatch(asset):
            raise HTTPException(404, "No such house asset")
        headers = {name: request.headers[name] for name in ("if-none-match", "if-modified-since")
                   if name in request.headers}
        return await simulator_read(f"/sim/assets/house/{asset}", headers)

    @application.get("/demo/api/sim/{view}")
    async def sim_read(view: str):
        if view not in SIM_READS:
            raise HTTPException(404, "No such viewer route")
        return await simulator_read(SIM_READS[view])

    @application.get("/demo/api/config")
    def config():
        cfg = demo_config()
        return {
            "household_id": cfg["household"],
            "server": bool(cfg["server"]),
            "hub": bool(cfg["hub"]),
            "fixture": cfg["fixture"],
            "story_timing": story_timing(),
            **({"fixture_shares": fixture_shares()} if cfg["fixture"] else {}),
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
                    data={"household_id": cfg["household"]}, files=files,
                )

            if cfg["fixture"]:
                # Keep this shell's shares in order around the fixture's one-shot override.
                async with fixture_share:
                    if sample:
                        selection = await client.post(
                            f"{cfg['server']}/_fixture/scene/next-order", headers=auth,
                            json={"episode_id": SAMPLE_EPISODES[sample],
                                  "starts_in_seconds": int(os.getenv("DEMO_STARTS_IN") or "90")},
                        )
                        if not selection.is_success:
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
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                upstream = await client.get(f"{cfg['hub']}/state")
            if not upstream.is_success:
                raise HTTPException(502, "Hub state is unavailable")
            body = upstream.json()
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(502, "Hub state is unavailable") from error
        ledger, guest_windows = story_ledger(body)
        return {
            "ledger": ledger, "waiting": body.get("waiting", []), "guest_windows": guest_windows,
            "plan_actions": received_actions(body),
        }

    @application.post("/demo/api/home/{action}")
    async def home_event(action: str, request: Request):
        """The timeline's world events (package, guests, end): the same as the operator's."""
        same_origin(request)
        if action not in HOME_ACTIONS:
            raise HTTPException(404, "No such home event")
        simulator = (os.getenv("DEMO_SIMULATOR_URL") or "").rstrip("/")
        token = os.getenv("DEMO_OPERATOR_TOKEN")
        if not simulator or not token:
            raise HTTPException(503, "Simulator operator is not configured")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                upstream = await client.post(
                    f"{simulator}/operator/home", auth=("operator", token), json={"action": action},
                )
            return JSONResponse(upstream.json(), status_code=upstream.status_code)
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(502, "Simulator operator is unavailable") from error

    @application.middleware("http")
    async def prevent_api_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/demo/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return application


app = create_app()
