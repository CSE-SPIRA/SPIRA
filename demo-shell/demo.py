"""Demo shell with the phone beside the Server's reasoning or the 3D house.

The shell reads only the team contract (episode, rationale, cards) through a
small allow-listed proxy, the World snapshot, and the Hub's read-only state.
Nothing here decides what the house does.
"""

import asyncio
import os
import re
import runpy
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from urllib.parse import urlencode

import httpx
import yaml
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from spira_contracts.plan import Action
from spira_contracts.reaction import Reaction

from recordings import RECORDING_ID, Batch, Label, RecordingStore, directory
from tagger import TagCache, Tagger

DEMO_UI = Path(__file__).with_name("ui")
LOOPBACK = {"127.0.0.1", "::1"}
THREE_MODULE = "three.module.min.js"
HOUSE_ASSET = re.compile(
    r"(?:fonts/)?[a-zA-Z0-9_.-]+\.(?:css|js|json|svg|jpg|png|woff2|txt)|vendor/three\.module\.min\.js"
)
EPISODE_READ = re.compile(r"v1/episodes/(ep_[A-Za-z0-9_]+)(/rationale)?")
EPISODE_ID = re.compile(r"ep_[A-Za-z0-9_]+")
DESIGN = runpy.run_path(str(DEMO_UI.parents[1] / "design/build.py"))
FONTS = {f"IBMPlexSansKR-{name}.otf": weight for weight, name in
         [(400, "Regular"), (500, "Medium"), (600, "SemiBold"), (700, "Bold")]}
SHARED_ASSETS = {
    "tokens.css": (DESIGN["css_tokens"](DESIGN["read"]("tokens.json")), "text/css"),
    "vocabulary.js": (DESIGN["js_vocabulary"](DESIGN["read"]("vocabulary.json")), "text/javascript"),
    "fonts.css": ("\n".join(
        f'@font-face {{font-family:"IBM Plex Sans KR";src:url("fonts/{name}");'
        f'font-weight:{weight};font-display:swap}}' for name, weight in FONTS.items()
    ), "text/css"),
}
# Read-only contract routes the shell may use.
SERVER_READS = (
    re.compile(r"^v1/episodes/ep_[A-Za-z0-9_]+$"),
    re.compile(r"^v1/episodes/ep_[A-Za-z0-9_]+/rationale$"),
    re.compile(r"^v1/households/h_[A-Za-z0-9_]+/cards$"),
    re.compile(r"^v1/demo/(clock|moments)$"),
    re.compile(r"^v1/demo/episodes/ep_[A-Za-z0-9_]+/trace$"),
    re.compile(r"^v1/demo/households/h_[A-Za-z0-9_]+/replays$"),
    re.compile(r"^v1/households/h_[A-Za-z0-9_]+/memory$"),
)
SAMPLE_EPISODES = {"birthday": "ep_9031", "groceries": "ep_9150"}
HOME_ACTIONS = {"delivery", "guests_arrive", "event_end"}
# A resident's own change at the device panel, as the operator page sends it.
PERSON_ACTIONS = {
    "mom_light": {"target": "mqtt:light_01", "actor": "resident", "actor_name": "엄마",
                  "action_path": "device_panel", "values": {"color": {"kelvin": 2700}}},
}
SIM_READS = {"snapshot": "/sim/snapshot", "viewer": "/sim/viewer?fragment=true"}
COMMAND_PROPERTIES = {"color": "color", "play_mood": "play_mood", "set_cook_standby": "preset",
                      "show_notice": "show_notice", "clean": "clean"}
STORY_TIMING_KEYS = ("before_start_default_min", "guest_window_before_min", "end_fallback_min")
HOUSE_EVENTS = {"package.brought_in", "guest_arrived", "event_end", "light.changed"}


def demo_config():
    return {
        "server": (os.getenv("DEMO_SERVER_URL") or "").rstrip("/"),
        "token": os.getenv("DEMO_APP_TOKEN") or "",
        "hub": (os.getenv("DEMO_HUB_URL") or "").rstrip("/"),
        "fixture": bool(os.getenv("DEMO_FIXTURE_EPISODE")),
        "household": os.getenv("DEMO_HOUSEHOLD", "h_042"),
    }


def server_headers(config):
    headers = {"Authorization": f"Bearer {config['token']}"}
    if config["fixture"]:
        headers["X-SPIRA-Demo-Client"] = "shell"
    return headers


def story_timing():
    path = os.getenv("DEMO_NUMBERS_PATH")
    if not path:
        return None
    try:
        numbers = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        timing = {key: {"normal": numbers[key], "demo": numbers["demo"][key]} for key in STORY_TIMING_KEYS}
    except (OSError, ValueError, yaml.YAMLError, KeyError, TypeError):
        return None
    if any(type(value) is not int or value < 0 for pair in timing.values() for value in pair.values()):
        return None
    return timing


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


def scene_relations(body):
    """Expose timing and verified device reads from the Hub's task relations."""
    plans = {}
    for story in body.get("task_stories", []):
        trigger = match = None
        observed = []
        for step in story["steps"]:
            if step["kind"] == "waiting":
                trigger = step["trigger"]
            elif step["kind"] == "triggered":
                match = {key: step[key] for key in ("at", "event_type") if key in step}
            elif (step.get("phase") == "run" and step.get("status") in {"running", "completed"}
                  and (reading := step.get("read_back")) and reading.get("available")
                  and (at := reading.get("occurred_at"))):
                desired = step.get("desired") or {}
                values = {key: value for key, value in reading["values"].items()
                          if key in desired or key in {"in_use", "job_status"}}
                observed.append({"device": step["device"], "cmd": step["cmd"], "at": at,
                                 "values": values, "revisions": reading["revisions"]})
        if trigger or observed:
            plans.setdefault(story["plan_id"], {})[story["task_id"]] = {
                "trigger": trigger, "match": match, "observed": observed,
            }
    return plans


def guest_windows(body: dict) -> dict:
    """Read the received guest windows used to align the card and house clocks."""
    windows = {}
    for story in body.get("task_stories", []):
        for step in story["steps"]:
            if step["kind"] != "waiting":
                continue
            trigger = step["trigger"]
            if trigger.get("event") == "guest_arrived" and trigger.get("window"):
                windows.setdefault(story["plan_id"], {})[story["task_id"]] = trigger["window"]
    return windows


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
        for name in ("content-type", "cache-control", "content-security-policy", "etag", "last-modified")
        if name in upstream.headers
    })


def create_app():
    application = FastAPI(title="SPIRA demo shell", docs_url=None, redoc_url=None, openapi_url=None)
    fixture_share = asyncio.Lock()
    recordings = RecordingStore()
    tagger = Tagger(TagCache(directory()), recordings.save_tags)
    application.mount("/demo/assets", StaticFiles(directory=DEMO_UI), name="demo-assets")

    @application.get("/demo")
    def demo_page(request: Request):
        query = request.query_params
        if query.get("replay") == "1" and query.get("episode") and not query.get("recording"):
            match = next((entry for entry in recordings.index()
                          if entry["episode_id"] == query["episode"] and entry["complete"]), None)
            if match:
                flags = {key: value for key, value in query.items() if key in ("dwell", "auto", "owners")}
                return RedirectResponse("/demo?" + urlencode({"recording": match["id"], **flags}))
        page = "recordings.html" if "recordings" in query else "index.html"
        return FileResponse(DEMO_UI / page, media_type="text/html")

    @application.get("/demo/artwork")
    def artwork_preview(request: Request):
        if (request.client is None or request.client.host not in LOOPBACK
                or request.url.hostname not in LOOPBACK | {"localhost"}):
            raise HTTPException(404, "No such demo page")
        same_origin(request)
        return FileResponse(DEMO_UI.parent / "artwork-preview.html", media_type="text/html", headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
                "img-src data:; frame-ancestors 'none'; base-uri 'none'"
            ),
        })

    @application.get("/demo/api/recordings")
    def recording_index():
        return recordings.index()

    @application.get("/demo/api/recordings/{recording_id}")
    def recording_read(recording_id: str):
        try:
            return recordings.read(recording_id)
        except FileNotFoundError as error:
            raise HTTPException(404, "No such recording") from error

    @application.post("/demo/api/recordings/{recording_id}")
    async def recording_append(recording_id: str, batch: Batch, request: Request):
        same_origin(request)
        try:
            run = tagger.run(batch.episode_id, recording_id)
            return {"offset": recordings.append(recording_id, batch, run.result if run else None)}
        except FileNotFoundError as error:
            raise HTTPException(404, "No such recording") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @application.patch("/demo/api/recordings/{recording_id}", status_code=204)
    def recording_label(recording_id: str, label: Label, request: Request):
        same_origin(request)
        try:
            recordings.label(recording_id, label)
        except FileNotFoundError as error:
            raise HTTPException(404, "No such recording") from error
        return Response(status_code=204)

    @application.get("/demo/shared/{asset}")
    def shared_asset(asset: str):
        if asset not in SHARED_ASSETS:
            raise HTTPException(404, "No such shared asset")
        content, media_type = SHARED_ASSETS[asset]
        return Response(content, media_type=media_type)

    @application.get("/demo/shared/fonts/{asset}")
    def shared_font(asset: str):
        if asset not in FONTS:
            raise HTTPException(404, "No such shared font")
        return FileResponse(DESIGN["FONTS"] / asset, media_type="font/otf")

    @application.get("/demo/replay-house/{asset:path}")
    @application.get("/sim/assets/house/{asset:path}")
    async def house_asset(asset: str, request: Request):
        if not HOUSE_ASSET.fullmatch(asset):
            raise HTTPException(404, "No such house asset")
        cached = directory() / "house-assets" / asset
        if request.url.path.startswith("/demo/replay-house/"):
            if cached.is_file():
                return FileResponse(cached)
            if asset == f"vendor/{THREE_MODULE}":
                previous = cached.parent.parent / THREE_MODULE
                if previous.is_file():
                    return FileResponse(previous)
        response = await simulator_read(f"/sim/assets/house/{asset}")
        if response.status_code == 200:
            try:
                cached.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with NamedTemporaryFile(dir=cached.parent, delete=False) as target:
                    temp = Path(target.name)
                    try:
                        target.write(response.body)
                        target.close()
                        temp.replace(cached)
                    finally:
                        temp.unlink(missing_ok=True)
            except OSError:
                pass  # A cache write failure must not interrupt the live renderer.
        return response

    @application.get("/demo/tags")
    async def tags(episode: str, request: Request):
        run_id = request.headers.get("X-SPIRA-Demo-Run")
        run = tagger.run(episode, run_id)
        if not run:
            return {"ready": False, "tags": []}
        if run.result:
            return {"ready": True, "tags": run.result["data"]}
        return {"ready": False, "tags": run.cached or []}

    @application.get("/demo/api/sim/{view}")
    async def sim_read(view: str):
        if view not in SIM_READS:
            raise HTTPException(404, "No such viewer route")
        return await simulator_read(SIM_READS[view])

    @application.get("/demo/api/config")
    def config(request: Request):
        cfg = demo_config()
        result = {
            "household_id": cfg["household"],
            "server": bool(cfg["server"]),
            "hub": bool(cfg["hub"]),
            "fixture": cfg["fixture"],
            "story_timing": story_timing(),
            "tagger": cfg["fixture"] and tagger.enabled,
        }
        episode = request.headers.get("X-SPIRA-Demo-Episode")
        if episode:
            result["demo_path"] = recordings.latest_path(episode)
        launcher = bool(os.getenv("DEMO_RESET_URL") and os.getenv("DEMO_RESET_TOKEN"))
        if launcher or (cfg["server"] and not cfg["fixture"]):
            result["reset"] = True
        # The Server's demo home is written again too (contracts/openapi/demo.yaml); the page says so.
        result["server_reset"] = bool(cfg["server"] and not cfg["fixture"])
        return result

    @application.post("/demo/api/reset", status_code=204)
    async def reset_demo(request: Request):
        if (request.client is None or request.client.host not in LOOPBACK
                or request.url.hostname not in LOOPBACK | {"localhost"}):
            raise HTTPException(403, "Use the demo page on loopback")
        same_origin(request)
        cfg = demo_config()
        url, token = os.getenv("DEMO_RESET_URL"), os.getenv("DEMO_RESET_TOKEN")
        server = cfg["server"] and not cfg["fixture"]
        if not server and (not url or not token):
            raise HTTPException(503, "Launcher reset is unavailable")
        if server:
            # Demo home back to dev/home.yaml on the Server; the hub key stays (server/spec.md 12.5).
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(5, read=60)) as client:
                    upstream = await client.post(
                        f"{cfg['server']}/v1/demo/households/{cfg['household']}/reset", headers=server_headers(cfg))
            except httpx.RequestError as error:
                raise HTTPException(503, "Server reset is unavailable") from error
            if upstream.status_code != 200:
                raise HTTPException(503, "Server could not reset the demo home")
        if not url or not token:
            return Response(status_code=204)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5, read=180), trust_env=False) as client:
                upstream = await client.post(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.RequestError as error:
            raise HTTPException(503, "Launcher reset is unavailable") from error
        if upstream.status_code == 409:
            raise HTTPException(409, "A reset is already in progress")
        if upstream.status_code != 204:
            raise HTTPException(503, "Launcher could not restart the local peers")
        return Response(status_code=204)

    @application.post("/demo/api/keep/{episode}")
    async def keep_for_replay(episode: str, request: Request):
        # Keep a finished live run for the Server replay (contracts/openapi/demo.yaml).
        if (request.client is None or request.client.host not in LOOPBACK
                or request.url.hostname not in LOOPBACK | {"localhost"}):
            raise HTTPException(403, "Use the demo page on loopback")
        same_origin(request)
        cfg = demo_config()
        if not cfg["server"] or cfg["fixture"]:
            raise HTTPException(503, "The Server replay needs DEMO_SERVER_URL without a fixture")
        if not EPISODE_ID.fullmatch(episode):
            raise HTTPException(404, "Not an episode")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                upstream = await client.post(f"{cfg['server']}/v1/demo/episodes/{episode}/keep",
                                             headers=server_headers(cfg), json={"keep": True})
        except httpx.HTTPError as error:
            raise HTTPException(502, "Server is unavailable") from error
        try:
            body = upstream.json()
        except ValueError as error:
            raise HTTPException(502, "Server response was not JSON") from error
        return JSONResponse(body, status_code=upstream.status_code)

    @application.get("/demo/api/server/{path:path}")
    async def server_read(path: str, request: Request):
        cfg = demo_config()
        if not cfg["server"]:
            raise HTTPException(503, "DEMO_SERVER_URL is not set")
        if not any(rule.match(path) for rule in SERVER_READS):
            raise HTTPException(404, "Not a demo read")
        household = path.split("/")[3] if path.startswith("v1/demo/households/") else (
            path.split("/")[2] if path.startswith("v1/households/") else None)
        if household is not None and household != cfg["household"]:
            raise HTTPException(404, "Not the active household")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                upstream = await client.get(
                    f"{cfg['server']}/{path}",
                    params=dict(request.query_params),
                    headers=server_headers(cfg),
                )
        except httpx.TimeoutException as error:
            raise HTTPException(504, "Server read timed out") from error
        except httpx.HTTPError as error:
            raise HTTPException(502, "Server is unavailable") from error
        try:
            body = upstream.json()
        except ValueError as error:
            status = upstream.status_code if upstream.is_error else 502
            raise HTTPException(status, "Server response was not JSON") from error
        match = EPISODE_READ.fullmatch(path)
        run_id = request.headers.get("X-SPIRA-Demo-Run")
        if (cfg["fixture"] and upstream.is_success and match and request.headers.get("X-SPIRA-Demo-Replay") != "1"
                and (run_id is None or RECORDING_ID.fullmatch(run_id))):
            episode, rationale = match.groups()
            try:
                tagger.observe(episode, run_id, "rationale" if rationale else "episode", body, cfg["fixture"])
            except ValidationError:
                pass  # Preserve the Server response even if its text cannot be tagged.
        return JSONResponse(body, status_code=upstream.status_code)

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
        auth = server_headers(cfg)
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
                # Fixture only: keep the one-shot scene selection and upload together.
                async with fixture_share:
                    if sample:
                        selection = await client.post(
                            f"{cfg['server']}/_fixture/scene/next-order", headers=auth,
                            json={"episode_id": SAMPLE_EPISODES[sample]},
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
        ledger = body.get("ledger", [])
        actions = received_actions(body)
        result = {
            "ledger": [row for row in ledger
                       if row["kind"] == "plan" or row.get("event_type") in HOUSE_EVENTS],
            "guest_windows": guest_windows(body),
            "plan_actions": actions,
        }
        if relations := scene_relations(body):
            result["plan_lines"] = relations
        return result

    @application.post("/demo/api/home/{action}")
    async def home_event(action: str, request: Request):
        """The presenter uses the same World event controls as the operator."""
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

    @application.post("/demo/api/clock")
    @application.post("/demo/api/clock/next")
    async def advance_clock(request: Request, episode_id: str | None = None):
        """Forward rehearsal clock writes to the Server."""
        same_origin(request)
        cfg = demo_config()
        if not cfg["server"]:
            raise HTTPException(503, "DEMO_SERVER_URL is not set")
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "Invalid clock request")
        path = "/v1/demo/clock"
        params = {}
        if request.url.path.endswith("/next"):
            path += "/next"
            if episode_id:
                params["episode_id"] = episode_id
        elif not isinstance(body.get("advance_to"), str):
            raise HTTPException(400, "advance_to is required")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                upstream = await client.post(
                    cfg["server"] + path, json=body, params=params, headers=server_headers(cfg),
                )
        except httpx.TimeoutException as error:
            raise HTTPException(504, "Server clock timed out") from error
        except httpx.HTTPError as error:
            raise HTTPException(502, "Server clock is unavailable") from error
        return Response(upstream.content, status_code=upstream.status_code,
                        media_type=upstream.headers.get("content-type"))

    @application.post("/demo/api/reaction")
    async def card_reaction(request: Request):
        """Forward the App's per-line or per-card intervention."""
        same_origin(request)
        cfg = demo_config()
        if not cfg["server"]:
            raise HTTPException(503, "DEMO_SERVER_URL is not set")
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "Invalid card reaction")
        card_id, reaction, task_id = body.get("card_id"), body.get("reaction"), body.get("task_id")
        if not isinstance(card_id, str) or not re.fullmatch(r"nc_[A-Za-z0-9_]+", card_id):
            raise HTTPException(400, "card_id is required")
        if (reaction == "stop" and "task_id" in body) or (reaction != "stop" and task_id is None):
            raise HTTPException(400, "Invalid card reaction")
        try:
            payload = Reaction(reaction=reaction, task_id=task_id)
        except ValidationError as error:
            raise HTTPException(400, "Invalid card reaction") from error
        async with httpx.AsyncClient(timeout=10) as client:
            upstream = await client.post(
                f"{cfg['server']}/v1/cards/{card_id}/reactions",
                json=payload.model_dump(mode="json", exclude_none=True),
                headers=server_headers(cfg),
            )
        return JSONResponse(upstream.json(), status_code=upstream.status_code)

    @application.post("/demo/api/person/{action}")
    async def person_action(action: str, request: Request):
        same_origin(request)
        if action not in PERSON_ACTIONS:
            raise HTTPException(404, "No such person action")
        simulator = (os.getenv("DEMO_SIMULATOR_URL") or "").rstrip("/")
        token = os.getenv("DEMO_OPERATOR_TOKEN")
        if not simulator or not token:
            raise HTTPException(503, "Simulator operator is not configured")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                upstream = await client.post(
                    f"{simulator}/operator/device", auth=("operator", token), json=PERSON_ACTIONS[action],
                )
            return JSONResponse(upstream.json(), status_code=upstream.status_code)
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(502, "Simulator operator is unavailable") from error

    @application.middleware("http")
    async def prevent_api_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/demo/api/") or request.url.path == "/demo/tags":
            response.headers["Cache-Control"] = "no-store"
        return response

    return application


app = create_app()
