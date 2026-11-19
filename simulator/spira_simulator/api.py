"""HTTP composition for the read-only stage and private operator."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from secrets import compare_digest

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field

from .mqtt import Broker, DeviceProtocol
from .profile import DEFAULT_PROFILE, Profile, load_profile
from .sources import JsonSource, Source, judge, stage_overlay
from .world import LOCAL_ACTORS, InvalidMutation, World

UI = Path(__file__).with_name("ui")
basic = HTTPBasic(auto_error=False)
log = logging.getLogger(__name__)


class OperatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HomeAction(OperatorInput):
    action: str


class DeviceAction(OperatorInput):
    target: str
    actor: str
    values: dict = Field(default_factory=dict)
    start: bool = False


class FaultAction(OperatorInput):
    target: str
    fault: str
    mode: str


def env_source(name: str, token_name: str, *, hub_key: bool = False) -> Source | None:
    value = os.getenv(name)
    if not value:
        return None
    token = os.getenv(token_name)
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
    broker_enabled: bool = True,
    received_source: Source | None = None,
    plan_source: Source | None = None,
    execution_source: Source | None = None,
) -> FastAPI:
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
        if enabled and not token:
            raise RuntimeError("WORLD_OPERATOR_TOKEN is required when WORLD_OPERATOR=1")
        config = profile or load_profile(
            Path(os.getenv("WORLD_PROFILE") or DEFAULT_PROFILE)
        )
        path = db_path or Path(os.getenv("WORLD_DB") or ".local/world.db")
        prefix = os.getenv("MQTT_PREFIX") or "spira/g0"
        world = World(path, config)
        broker = None
        timer = None
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
            app.state.operator_token = token if enabled else None
            app.state.received = received_source or env_source(
                "WORLD_RECEIVED_URL", "WORLD_RECEIVED_TOKEN"
            )
            app.state.plans = plan_source or env_source(
                "WORLD_PLANS", "WORLD_PLANS_TOKEN", hub_key=True
            )
            app.state.executions = execution_source or env_source(
                "WORLD_EXECUTIONS", "WORLD_EXECUTIONS_TOKEN"
            )
            timer = asyncio.create_task(jobs(protocol))
            yield
        finally:
            try:
                if timer:
                    timer.cancel()
                    with suppress(asyncio.CancelledError):
                        await timer
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

    def require_operator(
        request: Request, credentials: HTTPBasicCredentials | None = Depends(basic)
    ):
        token = request.app.state.operator_token
        if token is None:
            raise HTTPException(404, "Operator disabled")
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
        broker = request.app.state.broker
        return {"status": "ready", "mqtt": broker.status() if broker else None}

    @application.get("/sim/snapshot")
    def snapshot(request: Request):
        return request.app.state.world.snapshot()

    @application.get("/sim/overlay")
    async def overlay(request: Request):
        state = request.app.state
        return await stage_overlay(
            state.world.profile.household_id, state.plans, state.executions
        )

    @application.get("/sim/viewer")
    def viewer():
        return FileResponse(UI / "viewer.html")

    @application.get("/sim/stage.js")
    def stage_js():
        return FileResponse(UI / "stage.js", media_type="text/javascript")

    @application.get("/sim/style.css")
    def style():
        return FileResponse(UI / "style.css", media_type="text/css")

    @application.get("/operator", dependencies=[Depends(require_operator)])
    def operator():
        return FileResponse(UI / "operator.html", headers={"Cache-Control": "no-store"})

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
        return apply(request, request.app.state.world.home_event, body.action)

    @application.post("/operator/device", dependencies=[Depends(require_operator)])
    def device(body: DeviceAction, request: Request):
        return apply(
            request,
            request.app.state.world.local_change,
            body.target,
            body.actor,
            body.values,
            start=body.start,
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
            )
        except (OSError, ValueError, httpx.HTTPError) as exc:
            log.info("Received C-3 source could not be read")
            raise HTTPException(
                502, "Received C-3 source unavailable or invalid"
            ) from exc

    @application.middleware("http")
    async def prevent_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(
            ("/operator", "/sim/snapshot", "/sim/overlay", "/health")
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    return application


def apply(request: Request, action, *args, **kwargs):
    try:
        request.app.state.protocol.dispatch(action, *args, **kwargs)
    except InvalidMutation as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"applied": True}


app = create_app()
