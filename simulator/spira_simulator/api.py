"""HTTP composition for the household stage and private operator."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from secrets import compare_digest
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .design_vocabulary import ROOM_NAMES
from .mqtt import Broker, DeviceProtocol
from .profile import DEFAULT_PROFILE, Profile, load_profile
from .sources import JsonSource, Source, judge, stage_overlay
from .surfaces import (
    device_controls,
    device_name,
    display_time,
    guest_window_status,
    home_event_controls,
    home_event_observation,
    peer_viewers,
    tiles,
    viewer_plan,
    viewer_world,
)
from .world import LOCAL_ACTORS, ActionPath, InvalidMutation, World

UI = Path(__file__).with_name("ui")
templates = Jinja2Templates(directory=UI)
basic = HTTPBasic(auto_error=False)
log = logging.getLogger(__name__)


class HouseAssets(StaticFiles):
    async def get_response(self, path, scope):
        if path == "three.module.min.js":
            path = "vendor/three.module.min.js"
        return await super().get_response(path, scope)


class OperatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HomeAction(OperatorInput):
    action: str


class DeviceAction(OperatorInput):
    target: str
    actor: str
    actor_name: str | None = None
    action_path: ActionPath | None = None
    values: dict = Field(default_factory=dict)
    start: bool = False


class FaultAction(OperatorInput):
    target: str
    fault: str
    mode: str


def env_source(
    name: str, token_name: str | None = None, *, hub_key: bool = False
) -> Source | None:
    value = os.getenv(name)
    if not value:
        return None
    token = os.getenv(token_name) if token_name else None
    headers = None
    if token:
        headers = (
            {"X-API-Key": token} if hub_key else {"Authorization": f"Bearer {token}"}
        )
    return JsonSource(value, headers)


def create_app(
    db_path: Path | None = None,
    *,
    profile: Profile | None = None,
    operator_enabled: bool | None = None,
    operator_token: str | None = None,
    bind_host: str | None = None,
    broker_enabled: bool = True,
    received_source: Source | None = None,
    plan_source: Source | None = None,
    execution_source: Source | None = None,
) -> FastAPI:
    # The launcher supplies its configured listen address. An ASGI request's
    # local address can be loopback even when the server listens on every interface.
    operator_loopback = bind_host == "127.0.0.1"

    async def jobs(protocol: DeviceProtocol):
        while True:
            await asyncio.sleep(0.2)
            protocol.dispatch(protocol.world.complete_due)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        enabled = (
            operator_enabled
            if operator_enabled is not None
            else os.getenv("WORLD_OPERATOR") == "1"
        )
        token = (
            operator_token
            if operator_token is not None
            else os.getenv("WORLD_OPERATOR_TOKEN")
        )
        if enabled and not operator_loopback and not token:
            raise RuntimeError("WORLD_OPERATOR_TOKEN is required when WORLD_OPERATOR=1")
        config = profile or load_profile(
            Path(os.getenv("WORLD_PROFILE") or DEFAULT_PROFILE)
        )
        path = db_path or Path(os.getenv("WORLD_DB") or ".local/world.db")
        prefix = os.getenv("MQTT_PREFIX") or "spira/g0"
        world = World(path, config)
        broker = None
        tasks = []
        try:
            if broker_enabled:
                broker = Broker(
                    world,
                    os.getenv("MQTT_HOST") or "127.0.0.1",
                    int(os.getenv("MQTT_PORT") or "1883"),
                    prefix,
                    os.getenv("MQTT_USERNAME"),
                    os.getenv("MQTT_PASSWORD"),
                )
                broker.start()
            protocol = (
                broker.protocol
                if broker
                else DeviceProtocol(world, prefix, lambda *a, **kw: None)
            )
            app.state.world = world
            app.state.broker = broker
            app.state.protocol = protocol
            app.state.operator_enabled = enabled
            app.state.operator_token = token
            app.state.peer_viewers = peer_viewers(os.getenv("WORLD_PEER_VIEWERS", ""))
            hub_state = env_source("WORLD_HUB_STATE_URL")
            app.state.evidence_from_hub = hub_state is not None
            app.state.received = hub_state or received_source or env_source(
                "WORLD_RECEIVED_URL", "WORLD_RECEIVED_TOKEN"
            )
            app.state.plans = (
                plan_source
                or env_source("WORLD_PLANS_URL", "WORLD_PLANS_TOKEN", hub_key=True)
                or env_source("WORLD_PLANS", "WORLD_PLANS_TOKEN", hub_key=True)
            )
            app.state.executions = hub_state or execution_source or env_source(
                "WORLD_EXECUTIONS", "WORLD_EXECUTIONS_TOKEN"
            )
            tasks.append(asyncio.create_task(jobs(protocol)))
            yield
        finally:
            try:
                for task in tasks:
                    task.cancel()
                for task in tasks:
                    with suppress(asyncio.CancelledError):
                        await task
            finally:
                try:
                    if broker:
                        await asyncio.to_thread(broker.close)
                finally:
                    world.store.close()

    application = FastAPI(
        title="SPIRA Simulator",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    def shell_origin():
        return os.getenv("WORLD_HOUSE_SHELL_ORIGIN", "").rstrip("/")

    async def require_operator(request: Request):
        if not request.app.state.operator_enabled:
            raise HTTPException(404, "Operator disabled")
        if operator_loopback:
            return
        token = request.app.state.operator_token
        credentials: HTTPBasicCredentials | None = await basic(request)
        if (
            credentials is None
            or credentials.username != "operator"
            or not compare_digest(credentials.password.encode(), token.encode())
        ):
            raise HTTPException(
                401,
                "Operator credentials required",
                headers={
                    "WWW-Authenticate": 'Basic realm="SPIRA operator"',
                },
            )

    @application.get("/")
    def index():
        return RedirectResponse("/sim/viewer")

    @application.get("/health")
    def health(request: Request):
        return {"status": "ready", "mqtt": mqtt_status(request)}

    @application.get("/sim/snapshot")
    def snapshot(request: Request):
        return request.app.state.world.snapshot()

    @application.get("/sim/overlay")
    async def overlay(request: Request):
        state = request.app.state
        return await stage_overlay(
            state.world.profile.household_id,
            state.plans,
            state.executions,
            now=state.world.clock(),
            from_hub=state.evidence_from_hub,
        )

    @application.get("/sim/viewer")
    async def viewer(request: Request, fragment: bool = False):
        world = request.app.state.world
        overlay_data = await overlay(request)
        display = viewer_world(world)
        names = {tile["id"]: tile["name"] for tile in display["tiles"]}
        planned, restores = viewer_plan(overlay_data, names)
        rooms = {}
        for tile in display["tiles"]:
            tile["planned"] = planned.pop(tile["id"], [])
            rooms.setdefault(tile["room"], []).append(tile)
        mqtt = mqtt_status(request) or {}
        gap = mqtt.get("last_gap_at")
        return templates.TemplateResponse(
            request,
            "home.html" if fragment else "viewer.html",
            {
                **display,
                "fragment": fragment,
                "person_names": [person.name for person in world.profile.demo_people]
                if request.app.state.operator_enabled else [],
                "person_controls": {
                    device.logical_id: (
                        device.target,
                        [
                            {"key": control.key, "label": control.label,
                             "values": control.values, "start": control.start}
                            for control in device_controls(device, appliance=False)
                        ],
                    )
                    for device in world.devices.values()
                } if request.app.state.operator_enabled else {},
                "person_endpoint": str(request.base_url).rstrip("/") + "/operator/person"
                if fragment and shell_origin() else "",
                "person_shell_origin": shell_origin() if fragment else "",
                "home": world.profile.display_name or "우리 집",
                "peers": request.app.state.peer_viewers,
                "rooms": rooms,
                "room_names": ROOM_NAMES,
                "unplaced": planned.items(),
                "has_preparation": overlay_data["has_preparation"],
                "overlay_errors": overlay_data["errors"],
                "restores": restores,
                "mqtt_online": mqtt.get("connected", False),
                "mqtt_gap": display_time(gap) if gap else None,
            },
        )

    @application.get("/sim/library")
    def library():
        return FileResponse(UI / "library.html", media_type="text/html")

    @application.get("/sim/stage.js")
    def stage_js():
        return FileResponse(UI / "stage.js", media_type="text/javascript")

    @application.get("/sim/style.css")
    def style():
        return FileResponse(UI / "style.css", media_type="text/css")

    application.mount("/sim/assets/house", HouseAssets(directory=UI / "house"))

    async def operator_window(request: Request):
        state = request.app.state
        return await stage_overlay(
            state.world.profile.household_id, state.plans, None, now=state.world.clock(),
        )

    @application.get("/operator/guest-window", dependencies=[Depends(require_operator)])
    async def operator_guest_window(request: Request):
        data = await operator_window(request)
        if data["errors"]:
            raise HTTPException(503, "Plan source unavailable")
        return guest_window_status(request.app.state.world, data["guest_windows"])

    @application.get("/operator", dependencies=[Depends(require_operator)])
    async def operator(request: Request):
        world = request.app.state.world
        data = await operator_window(request)
        return templates.TemplateResponse(
            request,
            "operator.html",
            {
                "home_events": home_event_controls(world),
                "guest_window": guest_window_status(world, data["guest_windows"]),
                "household_id": world.profile.household_id,
                "inventory": world.devices.values(),
                "people": world.profile.demo_people,
                "devices": [
                    (
                        device.target,
                        device_name(device),
                        device_controls(device, appliance=False),
                    )
                    for device in world.devices.values()
                ],
            },
        )

    @application.get("/app", dependencies=[Depends(require_operator)])
    def appliance_app(request: Request, person: str = ""):
        world = request.app.state.world
        people = world.profile.demo_people
        names = [entry.name for entry in people]
        default = "아빠" if "아빠" in names else next(iter(names), "")
        device_tiles = tiles(world, world.snapshot(for_display=True))
        return templates.TemplateResponse(
            request,
            "appliance.html",
            {
                "home": world.profile.display_name or "우리 집",
                "tiles": device_tiles,
                "room_names": ROOM_NAMES,
                "people": names,
                "selected": person if person in names else default,
                "controls": {
                    device.logical_id: (
                        device.target,
                        device_controls(device, appliance=True),
                    )
                    for device in world.devices.values()
                },
            },
        )

    @application.post(
        "/operator/person",
        name="panel_action",
        dependencies=[Depends(require_operator)],
    )
    @application.post(
        "/app/device", name="appliance_action", dependencies=[Depends(require_operator)]
    )
    def person_control(
        request: Request,
        target: str = Query(),
        person: str = Form(),
        control: str = Form(),
    ):
        world = request.app.state.world
        appliance = request.scope["route"].name == "appliance_action"
        origin = request.headers.get("origin")
        shell_request = not appliance and bool(origin) and origin == shell_origin()
        if origin is not None and origin != str(request.base_url).rstrip("/") and not shell_request:
            raise HTTPException(403, "이 화면에서 기기를 조작해 주세요")
        profile_person = next(
            (entry for entry in world.profile.demo_people if entry.name == person), None
        )
        device = world.devices.get(target)
        action = (
            next(
                (
                    entry
                    for entry in device_controls(device, appliance=appliance)
                    if entry.key == control
                ),
                None,
            )
            if device
            else None
        )
        if profile_person is None or action is None:
            raise HTTPException(400, "사용할 수 없는 기기 조작입니다")
        apply(
            request,
            world.local_change,
            target,
            profile_person.role,
            action.values,
            start=action.start,
            actor_name=profile_person.name,
            action_path="other_app" if appliance else "device_panel",
        )
        if not appliance and request.headers.get("accept") == "application/json":
            return {"applied": True}
        destination = (
            "/app?" + urlencode({"person": profile_person.name})
            if appliance
            else "/operator"
        )
        return RedirectResponse(destination, status_code=303)

    @application.get("/operator/ui.js", dependencies=[Depends(require_operator)])
    def operator_js():
        return FileResponse(UI / "operator.js", media_type="text/javascript")

    @application.get("/operator/options", dependencies=[Depends(require_operator)])
    def options(request: Request):
        world = request.app.state.world
        return {
            "actors": sorted(LOCAL_ACTORS),
            "home_actions": list(world.profile.home_signals),
            "devices": [
                {
                    "target": device.target,
                    "device_type": device.device_type,
                    "label": device.label,
                    "editable": [
                        key
                        for key, prop in device.properties.items()
                        if prop.local_write
                    ],
                    "start": bool(device.job and device.job.trigger_property is None),
                }
                for device in world.devices.values()
                if device.substrate == "virtual"
            ],
        }

    @application.post("/operator/home", dependencies=[Depends(require_operator)])
    def home(body: HomeAction, request: Request):
        signals = dispatch(request, request.app.state.world.home_event, body.action)
        return {"applied": True, **home_event_observation(signals[-1])}

    @application.post("/operator/device", dependencies=[Depends(require_operator)])
    def device(body: DeviceAction, request: Request):
        return apply(
            request,
            request.app.state.world.local_change,
            body.target,
            body.actor,
            body.values,
            start=body.start,
            actor_name=body.actor_name,
            action_path=body.action_path,
        )

    @application.post("/operator/fault", dependencies=[Depends(require_operator)])
    def fault(body: FaultAction, request: Request):
        return apply(
            request,
            request.app.state.world.set_fault,
            body.target,
            body.fault,
            body.mode,
        )

    @application.get("/operator/truth", dependencies=[Depends(require_operator)])
    def truth(
        request: Request,
        after: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
    ):
        return request.app.state.world.store.truth(after, limit)

    @application.get("/operator/snapshot", dependencies=[Depends(require_operator)])
    def operator_snapshot(request: Request):
        return request.app.state.world.snapshot(include_operator_actions=True)

    @application.get("/operator/judge", dependencies=[Depends(require_operator)])
    async def compare(request: Request):
        state = request.app.state
        if state.received is None:
            raise HTTPException(503, "Received C-3 source is unconfigured")
        try:
            return await judge(
                state.world.profile.household_id,
                state.world.store.truth(),
                state.received,
                from_hub=state.evidence_from_hub,
            )
        except (OSError, ValueError, httpx.HTTPError) as exc:
            log.info("Received C-3 source could not be read")
            raise HTTPException(
                502, "Received C-3 source unavailable or invalid"
            ) from exc

    @application.post("/operator/judge/marker", dependencies=[Depends(require_operator)])
    def mark_commands(request: Request):
        return request.app.state.world.mark_commands()

    @application.get("/operator/judge/commands", dependencies=[Depends(require_operator)])
    def count_commands(
        request: Request,
        start: AwareDatetime | None = None,
        end: AwareDatetime | None = None,
    ):
        if (start is None) != (end is None):
            raise HTTPException(400, "Provide both start and end, or use the marker")
        if start is not None and end is not None and end <= start:
            raise HTTPException(400, "End must be later than start")
        counts = request.app.state.world.command_counts(start, end)
        if counts is None:
            raise HTTPException(409, "Set a command marker or enter a time range")
        return counts

    @application.middleware("http")
    async def prevent_caching(request: Request, call_next):
        response = await call_next(request)
        origin = request.headers.get("origin")
        if request.url.path == "/operator/person" and origin and origin == shell_origin():
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
        if request.url.path.startswith(
            (
                "/operator",
                "/app",
                "/sim/viewer",
                "/sim/snapshot",
                "/sim/overlay",
                "/health",
            )
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    return application


def mqtt_status(request: Request):
    broker = request.app.state.broker
    return broker.status() if broker else None


def dispatch(request: Request, action, *args, **kwargs):
    try:
        return request.app.state.protocol.dispatch(action, *args, **kwargs)
    except InvalidMutation as exc:
        raise HTTPException(400, str(exc)) from exc


def apply(request: Request, action, *args, **kwargs):
    dispatch(request, action, *args, **kwargs)
    return {"applied": True}


app = create_app()
