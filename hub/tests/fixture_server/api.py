"""HTTP transport for the non-inference fixture replay."""

import logging
from base64 import b64decode
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import httpx2
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from spira_contracts.ack import Ack
from spira_contracts.calendar import Calendar
from spira_contracts.calendar_response import CalendarResponse
from spira_contracts.cards_response import CardsResponse
from spira_contracts.common import EpisodeStatus, HomeEvent
from spira_contracts.devices import Devices
from spira_contracts.devices_response import DevicesResponse
from spira_contracts.episode_list import Episode as EpisodeSummary
from spira_contracts.episode_list import EpisodeList
from spira_contracts.error import Error
from spira_contracts.event import Event
from spira_contracts.event_response import EventResponse, RejectedItem
from spira_contracts.execution_response import ExecutionResponse
from spira_contracts.execution_result import ExecutionResult
from spira_contracts.health import Health
from spira_contracts.household_create import HouseholdCreate
from spira_contracts.memory import Memory
from spira_contracts.order_accepted import OrderAccepted
from spira_contracts.order_edit import OrderEdit
from spira_contracts.pause import Pause
from spira_contracts.plan_pull import PlanPull
from spira_contracts.profile import Profile
from spira_contracts.reaction import Reaction
from spira_contracts.validate import ContractError, validate
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from .catalogue import CASES_BY_ID
from .control import (
    CaseAction, ClockAction, EpisodeAction, Pace, Realistic, Rehearsal, derive_plan,
    extend_quiet_window, hold_before, retime, stages,
)
from .control_transport import ConnectionDropped, Fault, Group, RehearsalTraffic, Traffic, local_control
from .moments import QUIET_END, plan_moments
from .observation import SEOUL, close_observation, record_memory
from .replay import CONTRACTS, EPISODES, JudgmentStage, Replay, read_json, valid_household_types, wire
from .scene_support import NextOrder, apply_scene_calendar, live_replay, realistic_schedule, server_numbers
from .story_clock import StoryClock, story_now

LABEL = "SPIRA fixture - non-inference test support"
LABEL_HEADER = "X-SPIRA-Fixture"
logger = logging.getLogger("uvicorn.error")
CONTROL = "/_fixture/control"
# The upload path validates the attachment; the selected recording supplies all content.
SAMPLE_PNG = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jO9sAAAAASUVORK5CYII=")


class ClockAdvanceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    over_seconds: Annotated[float, Field(ge=1, le=60)] = 6


class ClockAdvance(ClockAdvanceOptions):
    advance_to: str


class ClockJump(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    set_to: str


class FixtureError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.body = Error(code=code, message=f"{LABEL}. {message}")


def response(model, status=200):
    return JSONResponse(wire(model), status_code=status)


def parse(model, body):
    validate(body, model.__module__.rsplit(".", 1)[1] + ".json")
    return model.model_validate(body)


async def read_body(request: Request, model, *, receipts=None):
    try:
        body = await request.json()
        if receipts is not None:
            receipts.append(body)
        return parse(model, body)
    except ValueError as exc:
        raise FixtureError(422, "validation_error", "Invalid contract body") from exc


def timestamp(value: str | None):
    if value is None:
        return None
    try:
        validate(value, "common.json#/$defs/DateTime")
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise FixtureError(422, "validation_error", "Invalid timestamp") from exc


def create_app(
    episode_id: str = "ep_9031", *, scene_controls: bool = False, demo_mode: bool = False,
    default_scene: NextOrder | None = None, realistic_seed: int | None = None,
) -> FastAPI:
    # Keep demo_mode for existing fixture callers. Live scenes use the service quiet time.
    replay = Replay(episode_id)
    if default_scene and Replay(default_scene.episode_id).household_id != replay.household_id:
        raise ValueError("The default scene must belong to the fixture household")
    live_scenes = scene_controls or default_scene is not None
    clock = StoryClock(datetime.now(SEOUL))
    if live_scenes:
        replay.story_clock = clock
    snapshots: dict[str, Replay] = {} if live_scenes else {episode_id: replay}
    historical_package_replays: dict[str, Replay] = {}
    scene_counts: dict[str, int] = {}
    pending_order: NextOrder | None = None
    orders: dict[str, str] = {}
    event_ids: set[str] = set()
    result_ids: set[str] = set()
    traffic = Traffic()
    traffic.set_realistic(realistic_seed)
    rehearsal = Rehearsal()
    choices = [id_ for id_ in EPISODES if Replay(id_).household_id == replay.household_id]
    app = FastAPI(title=LABEL, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def identify_fixture(request: Request, call_next):
        result = await call_next(request)
        result.headers[LABEL_HEADER] = LABEL
        logger.info(
            "%s [%s] %s %s %s",
            LABEL,
            episode_id,
            request.method,
            request.url.path,
            result.status_code,
        )
        return result

    if live_scenes:
        app.add_middleware(RehearsalTraffic, traffic=traffic, label=LABEL, label_header=LABEL_HEADER)

    @app.exception_handler(FixtureError)
    async def fixture_error(_request, error):
        return response(error.body, error.status)

    @app.exception_handler(HTTPException)
    async def http_error(_request, error):
        code = "not_found" if error.status_code == 404 else "invalid_request"
        return response(
            Error(code=code, message=f"{LABEL}. {error.detail}"), error.status_code
        )

    def require_household(household_id: str, *, hub=False):
        if household_id != replay.household_id:
            status, code = (403, "forbidden") if hub else (404, "not_found")
            raise FixtureError(
                status, code, "Household is outside the selected fixture"
            )

    def require_episode(requested_episode: str):
        if requested_episode not in snapshots:
            raise FixtureError(
                404, "not_found", "Episode is outside the selected fixture"
            )
        return snapshots[requested_episode]

    def apply_calendar(calendar: Calendar):
        for event in calendar.events:
            timestamp(event.start)
            timestamp(event.end)
        if replay.live:
            apply_scene_calendar(replay, calendar)
        elif not live_scenes and calendar == replay.calendar:
            replay.find_calendar_time()
        return response(CalendarResponse(accepted=len(calendar.events)), 202)

    def apply_pause(paused: bool):
        for snapshot in snapshots.values() or (replay,):
            snapshot.pause(paused)
            if snapshot.live:
                snapshot.project()
        return response(Pause(household_id=replay.household_id, paused=replay.paused))

    def select_order(order):
        nonlocal pending_order
        if order.episode_id not in choices:
            raise FixtureError(422, "validation_error", "Scene episode belongs to another household")
        pending_order = order

    def refresh_observations():
        if not replay.live:
            return
        now = replay.now()
        active = [
            snapshot for snapshot in snapshots.values()
            if snapshot.card and snapshot.observation is None and snapshot.published()
        ]
        if not active:
            return
        events = sorted(
            (event for snapshot in snapshots.values() for event in snapshot.events.values()),
            key=lambda event: datetime.fromisoformat(event.at),
        )
        windows = [snapshot.observation_window for snapshot in snapshots.values()]
        for snapshot in active:
            start_at = close_observation(snapshot, events, windows, now)
            if start_at is not None:
                intent_names = {entry["id"]: entry["name"] for entry in read_json(CONTRACTS / "kb/intents.json")["intents"]}
                record_memory(snapshot, start_at, intent_names, server_numbers()["line_off_d"])

    def release_package(event: Event) -> bool:
        for snapshot in reversed(snapshots.values()):
            if snapshot.published() and snapshot.release_package(event):
                snapshot.events[event.event_id] = event
                if snapshot is not replay:
                    historical_package_replays[snapshot.plan.plan_id] = snapshot
                    snapshot.project()
                return True
        return False

    async def app_token(request: Request):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise FixtureError(
                401, "unauthorized", "A placeholder Bearer token is required"
            )

    async def hub_key(request: Request):
        if request.headers.get("X-API-Key") != replay.onboarding.hub_api_key:
            raise FixtureError(
                401, "unauthorized", "The fixture placeholder X-API-Key is required"
            )

    app_auth = [Depends(app_token)]
    hub_auth = [Depends(hub_key)]

    @app.get("/health")
    async def health():
        return response(Health(status="ok"))

    @app.get("/_fixture/receipts")
    async def receipts():
        return JSONResponse(replay.receipts)

    if live_scenes:
        def clock_response(real_now: datetime):
            state = clock.state
            body = state.model_dump(mode="json")
            if not state.rate:
                # The existing Hub clock reader validates a positive rate.
                # This stays frozen at its datetime resolution.
                body["rate"] = 1e-20
            return {**body, "now": story_now(state, real_now).isoformat()}

        def advance_clock(target: datetime, real_now: datetime, seconds: float):
            try:
                clock.advance(target, real_now, seconds)
            except ValueError as exc:
                raise FixtureError(409, "invalid_request", str(exc)) from exc

        @app.get("/v1/demo/clock")
        async def get_clock():
            return clock_response(datetime.now(SEOUL))

        @app.post("/v1/demo/clock")
        async def post_clock(change: ClockJump | ClockAdvance):
            real_now = datetime.now(SEOUL)
            if isinstance(change, ClockJump):
                clock.set(timestamp(change.set_to).astimezone(SEOUL), real_now)
            else:
                advance_clock(timestamp(change.advance_to).astimezone(SEOUL), real_now, change.over_seconds)
            return clock_response(real_now)

        @app.get("/v1/demo/moments")
        async def get_moments():
            return plan_moments(replay) if snapshots else []

        def move_to_moment(real_now, seconds, moment_id=None):
            now = story_now(clock.state, real_now)
            for moment in plan_moments(replay) if snapshots else ():
                if moment_id is not None and moment["id"] != moment_id:
                    continue
                at = datetime.fromisoformat(moment["at"])
                if at > now:
                    target = at
                    if moment["kind"] == "time" and moment["event"] != QUIET_END:
                        target -= timedelta(seconds=20)
                    advance_clock(target, real_now, seconds)
                    return moment
            raise FixtureError(404, "not_found", "No story moments remain")

        @app.post("/v1/demo/clock/next")
        async def next_moment(options: ClockAdvanceOptions | None = None):
            return move_to_moment(datetime.now(SEOUL), (options or ClockAdvanceOptions()).over_seconds)

    if scene_controls:
        @app.post("/_fixture/scene/next-order", dependencies=app_auth, status_code=202)
        async def next_order(order: NextOrder):
            select_order(order)
            return {"episode_id": order.episode_id, "household_id": replay.household_id}

        @app.post("/_fixture/scene/calendar", dependencies=app_auth, status_code=202)
        async def post_scene_calendar():
            if not replay.live or not replay.calendar:
                raise FixtureError(404, "not_found", "No committed calendar for the active scene")
            return apply_calendar(replay.calendar)

        @app.get("/_fixture/scene/acks", dependencies=hub_auth)
        async def scene_acks():
            return JSONResponse([wire(ack) for ack in replay.acks.values()])

    @app.post("/v1/households", dependencies=app_auth)
    async def create_household(request: Request):
        profile = await read_body(request, HouseholdCreate)
        replay.profile = profile.household_types
        return response(replay.onboarding, 201)

    @app.put("/v1/households/{household_id}/profile", dependencies=app_auth)
    async def put_profile(household_id: str, request: Request):
        require_household(household_id)
        profile = await read_body(request, Profile)
        if not valid_household_types(profile.household_types):
            raise FixtureError(
                422,
                "household_types_invalid",
                "Household types fail the contract's profile rules",
            )
        replay.profile = profile.household_types
        return response(
            Profile(household_id=household_id, household_types=replay.profile)
        )

    @app.put("/v1/households/{household_id}/calendar", dependencies=app_auth)
    async def put_calendar(household_id: str, request: Request):
        require_household(household_id)
        calendar = await read_body(request, Calendar)
        return apply_calendar(calendar)

    @app.post("/v1/households/{household_id}/pause", dependencies=app_auth)
    async def put_pause(household_id: str, request: Request):
        require_household(household_id)
        pause = await read_body(request, Pause)
        return apply_pause(pause.paused)

    @app.get("/v1/households/{household_id}/episodes", dependencies=app_auth)
    async def get_episodes(household_id: str, request: Request):
        require_household(household_id)
        before = timestamp(request.query_params.get("before"))
        try:
            limit = int(request.query_params.get("limit", "20"))
            if not 1 <= limit <= 100:
                raise ValueError
        except ValueError as exc:
            raise FixtureError(
                422, "validation_error", "Invalid episode limit"
            ) from exc
        if replay.live and replay.published():
            replay.project()
        episodes = [
            EpisodeSummary(
                episode_id=episode.episode_id,
                shared_at=episode.shared_at,
                status=episode.status,
                item_count=episode.item_count,
                card_ids=episode.card_ids,
            )
            for episode in (snapshot.episode_detail() for snapshot in reversed(snapshots.values()))
            if before is None or datetime.fromisoformat(episode.shared_at) < before
        ]
        episodes.sort(key=lambda episode: datetime.fromisoformat(episode.shared_at), reverse=True)
        next_before = episodes[limit - 1].shared_at if len(episodes) > limit else None
        return response(EpisodeList(episodes=episodes[:limit], next_before=next_before))

    @app.get("/v1/households/{household_id}/cards", dependencies=app_auth)
    async def get_cards(household_id: str, request: Request):
        require_household(household_id)
        since = timestamp(request.query_params.get("since"))
        if replay.live and replay.published():
            replay.project()
        cards = []
        now = replay.now()
        if live_scenes and since is not None and since > now:
            since = None  # An offset reset can put the App's cursor ahead of the clock.
        for snapshot in reversed(snapshots.values()):
            card = snapshot.card
            if card is None or not snapshot.published():
                continue
            if since is None:
                if snapshot.episode.status != EpisodeStatus.CLOSED and not card.stopped:
                    cards.append(card)
            elif datetime.fromisoformat(card.updated_at) > since:
                cards.append(card)
        return response(
            CardsResponse(cards=cards, server_time=now.isoformat())
        )

    @app.get("/v1/households/{household_id}/memory", dependencies=app_auth)
    async def get_memory(household_id: str):
        require_household(household_id)
        if not replay.live:
            return response(replay.memory)
        refresh_observations()
        groups = {}
        for snapshot in reversed(snapshots.values()):
            for intent in snapshot.memory.intents:
                key = (intent.intent_id, frozenset(intent.calendar_tags))
                if key in groups:
                    group = groups[key]
                    group.episodes.extend(intent.episodes)
                    group.off_lines.extend(intent.off_lines)
                    group.changed.extend(intent.changed)
                else:
                    groups[key] = intent.model_copy(deep=True)
        return response(Memory(household_id=household_id, intents=list(groups.values())))

    @app.delete("/v1/households/{household_id}/memory/{case_id}", dependencies=app_auth)
    async def forget_case(household_id: str, case_id: str):
        require_household(household_id)
        refresh_observations()
        for snapshot in snapshots.values() or (replay,):
            for intent in snapshot.memory.intents:
                if any(episode.case_id == case_id for episode in intent.episodes):
                    intent.episodes = [
                        episode for episode in intent.episodes if episode.case_id != case_id
                    ]
                    intent.off_lines = [
                        line for line in intent.off_lines if line.case_id != case_id
                    ]
                    intent.changed = [
                        change for change in intent.changed if change.case_id != case_id
                    ]
                    snapshot.memory.intents = [
                        entry for entry in snapshot.memory.intents if entry.episodes
                    ]
                    return Response(status_code=204)
        raise FixtureError(404, "not_found", "No such case in the replayed memory")

    @app.post("/v1/orders", dependencies=app_auth)
    async def post_order(request: Request):
        nonlocal replay, pending_order
        try:
            async with request.form() as form:
                household = form.get("household_id")
                validate(household, "common.json#/$defs/HouseholdId")
                require_household(household)
                shared_at = form.get("shared_at")
                if shared_at is not None:
                    validate(shared_at, "common.json#/$defs/DateTime")
                source_id = form.get("source_id")
                if source_id is not None and not isinstance(source_id, str):
                    raise ContractError("source_id must be a string")
                images = form.getlist("images")
                if not 1 <= len(images) <= 3 or any(
                    not isinstance(image, UploadFile)
                    or image.content_type not in ("image/jpeg", "image/png")
                    or not 0 < image.size <= 5 * 1024 * 1024
                    for image in images
                ):
                    raise FixtureError(
                        400, "invalid_image", "Expected one to three JPEG or PNG parts"
                    )
        except (ContractError, HTTPException) as exc:
            raise FixtureError(
                400, "invalid_request", "Invalid multipart order"
            ) from exc
        duplicate = source_id in orders
        skipped = replay.paused and rehearsal.active_case == "paused-share"
        if not duplicate and live_scenes and (not replay.paused or skipped):
            scene = pending_order or default_scene
            if scene is None and (rehearsal.next_pace or rehearsal.share_mode or skipped or traffic.realistic_seed is not None):
                scene = NextOrder(episode_id=episode_id)
            if scene is None and not snapshots:
                raise FixtureError(409, "invalid_request", "Select a scene episode before upload")
            capture = (
                rehearsal.capture_episode == replay.episode.episode_id and not replay.paused
                and (pending_order is None or pending_order.episode_id == "ep_9031")
                and replay.quiet_end is not None and replay.now() < replay.quiet_end
            )
            if capture:
                extend_quiet_window(replay)
                rehearsal.capture_episode = None
                pending_order = None
            elif scene is not None or skipped:
                scene = scene or NextOrder(episode_id=episode_id)
                template = scene.episode_id
                scene_counts[template] = scene_counts.get(template, 0) + 1
                pace = None
                if not skipped:
                    if rehearsal.next_pace:
                        pace = rehearsal.next_pace.schedule()
                    elif traffic.realistic_seed is not None:
                        pace = realistic_schedule(traffic.realistic_seed, scene_counts[template])
                upcoming = live_replay(scene, clock=clock, sequence=scene_counts[template], pace=pace)
                if skipped:
                    upcoming.skipped = upcoming.paused = True
                    upcoming.judgment_at = {}
                    upcoming.quiet_end = None
                    upcoming.episode = upcoming.episode.model_copy(update={
                        "shared_at": shared_at or replay.now().isoformat(),
                        "status": EpisodeStatus.PAUSED_SKIP, "items": [], "item_count": 0,
                        "masked_count": 0, "item_tasks": [], "card_ids": [],
                    })
                else:
                    clock.set(datetime.fromisoformat(upcoming.episode.shared_at).astimezone(SEOUL), datetime.now(SEOUL))
                    if rehearsal.next_pace:
                        upcoming.judgment_hold = hold_before(rehearsal.next_pace.hold)
                    if rehearsal.share_mode == "read_failed":
                        upcoming.read_failure = True
                    if rehearsal.share_mode == "second_capture" and template == "ep_9031":
                        rehearsal.capture_episode = upcoming.episode.episode_id
                    if rehearsal.derive_next and template == "ep_9031":
                        derive_plan(upcoming, rehearsal.derive_next)
                    rehearsal.next_pace = rehearsal.share_mode = rehearsal.derive_next = None
                    rehearsal.resend_version = None
                    pending_order = None
                upcoming.devices = replay.devices
                upcoming.profile = replay.profile
                upcoming.receipts = replay.receipts
                snapshots[upcoming.episode.episode_id] = upcoming
                replay = upcoming
        selected_id = orders[source_id] if duplicate else replay.episode.episode_id
        if source_id is not None:
            orders[source_id] = selected_id
        status = EpisodeStatus.PAUSED_SKIP if replay.paused else EpisodeStatus.RECEIVED
        return response(
            OrderAccepted(episode_id=selected_id, status=status),
            200 if duplicate else 202,
        )

    @app.get("/v1/episodes/{episode_id}", dependencies=app_auth)
    async def get_episode(episode_id: str):
        snapshot = require_episode(episode_id)
        if snapshot is replay and replay.live and replay.published():
            replay.project()
        return response(snapshot.episode_detail())

    @app.put("/v1/episodes/{episode_id}/order", dependencies=app_auth)
    async def edit_order(episode_id: str, request: Request):
        require_episode(episode_id)
        await read_body(request, OrderEdit)
        status = EpisodeStatus.PAUSED_SKIP if replay.paused else EpisodeStatus.RECEIVED
        return response(OrderAccepted(episode_id=episode_id, status=status), 202)

    @app.get("/v1/episodes/{episode_id}/rationale", dependencies=app_auth)
    async def get_rationale(episode_id: str):
        snapshot = require_episode(episode_id)
        rationale = snapshot.rationale_detail()
        if rationale is None:
            raise FixtureError(
                404, "not_found", "No rationale snapshot at this fixture step"
            )
        if snapshot.live:
            refresh_observations()
            rationale.executions = snapshot.rationale_executions()
            rationale.observations = [snapshot.observation] if snapshot.observation else []
        return response(rationale)

    @app.post("/v1/cards/{card_id}/reactions", dependencies=app_auth)
    async def react(card_id: str, request: Request):
        reaction = await read_body(request, Reaction)
        if not snapshots or not replay.card or replay.card.card_id != card_id or replay.finished or not replay.published():
            raise FixtureError(
                404, "not_found", "No open card with this ID in the fixture"
            )
        try:
            refresh_observations()
            replay.react(reaction)
            if replay.live:
                replay.project()
                refresh_observations()
            return response(replay.card)
        except LookupError as exc:
            raise FixtureError(404, "not_found", str(exc)) from exc
        except ValueError as exc:
            raise FixtureError(409, "line_started", str(exc)) from exc

    @app.put("/v1/hub/households/{household_id}/devices", dependencies=hub_auth)
    async def put_devices(household_id: str, request: Request):
        require_household(household_id, hub=True)
        devices = await read_body(request, Devices)
        require_household(devices.household_id, hub=True)
        if devices.revision <= replay.devices.revision and devices != replay.devices:
            raise FixtureError(
                409,
                "stale_revision",
                "Device registration does not advance the fixture revision",
            )
        replay.devices = devices
        return response(DevicesResponse(revision=devices.revision))

    @app.get("/v1/hub/plans", dependencies=hub_auth)
    async def get_plans(request: Request):
        require_household(request.query_params.get("household"), hub=True)
        plans = [replay.plan] if snapshots and not replay.finished and replay.published() else []
        if replay.skipped or replay.read_failure:
            previous = next((entry for entry in reversed(snapshots.values()) if not entry.finished and entry.published()), None)
            if previous and previous.plan.plan_id not in historical_package_replays:
                plans.append(previous.plan)
        if plans and rehearsal.resend_version:
            plan_id, version = rehearsal.resend_version
            if plan_id == replay.plan.plan_id:
                plans[0] = replay.plans[version]
            rehearsal.resend_version = None
        plans.extend(snapshot.plan for snapshot in historical_package_replays.values())
        rehearsal.record_pull(plans)
        return response(
            PlanPull(
                household_id=replay.household_id,
                paused=replay.paused,
                devices_revision=replay.devices.revision,
                plans=plans,
            )
        )

    @app.post("/v1/hub/plans/{plan_id}/ack", dependencies=hub_auth)
    async def ack_plan(plan_id: str, request: Request):
        ack = await read_body(request, Ack)
        snapshot = require_episode(plan_id)
        snapshot.acks[ack.plan_version] = ack
        rehearsal.acked_at[plan_id, ack.plan_version] = datetime.now(SEOUL).isoformat()
        if snapshot.live:
            snapshot.project()
        return Response(status_code=204)

    @app.post("/v1/hub/events", dependencies=hub_auth)
    async def post_events(request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        else:
            replay.receipts["events"].append(body)
        if not isinstance(body, list) or not body:
            return response(
                EventResponse(
                    accepted=[],
                    plans_changed=False,
                    rejected=[
                        RejectedItem(
                            event_id="",
                            code="validation_error",
                            message=f"{LABEL}. Expected a nonempty event batch",
                        )
                    ],
                )
            )
        if any(
            isinstance(event, dict)
            and event.get("household_id") not in (None, replay.household_id)
            for event in body
        ):
            raise FixtureError(
                403, "forbidden", "Event batch contains a different household"
            )
        accepted, rejected = [], []
        changed = False
        device_ids = {device.id for device in replay.devices.devices}
        for raw in body:
            try:
                event = parse(Event, raw)
                datetime.fromisoformat(event.at)
                if event.event_id not in event_ids:
                    if event.source != "hub" and event.source not in device_ids:
                        raise ContractError("Unknown fixture device")
                    event_ids.add(event.event_id)
                    if event.type == HomeEvent.PACKAGE_BROUGHT_IN and release_package(event):
                        changed = True
                    elif snapshots:
                        replay.events[event.event_id] = event
                accepted.append(event.event_id)
            except ValueError:
                event_id = raw.get("event_id") if isinstance(raw, dict) else None
                rejected.append(
                    RejectedItem(
                        event_id=event_id if isinstance(event_id, str) else "",
                        code="validation_error",
                        message=f"{LABEL}. Invalid event or unknown fixture device",
                    )
                )
        if replay.live and replay.published():
            replay.project()
            refresh_observations()
        changed = replay.finish_if_replayed() or changed
        return response(
            EventResponse(accepted=accepted, rejected=rejected, plans_changed=changed)
        )

    @app.post("/v1/hub/executions", dependencies=hub_auth)
    async def post_execution(request: Request):
        receipts = replay.receipts["executions"]
        result = await read_body(request, ExecutionResult, receipts=receipts)
        timestamp(result.root.at)
        snapshot = require_episode(result.root.plan_id)
        result_id = result.root.result_id
        duplicate = result_id in result_ids
        if not duplicate:
            result_ids.add(result_id)
            snapshot.results[result_id] = result
            snapshot.result_bodies[result_id] = receipts[-1]
            if not snapshot.finished:
                snapshot.project()
                refresh_observations()
            snapshot.finish_if_replayed()
        return response(ExecutionResponse(duplicate=duplicate))

    if live_scenes:
        async def require_loopback(request: Request):
            if not local_control(request):
                raise FixtureError(403, "forbidden", "Fixture control requires a loopback request")

        local = [Depends(require_loopback)]

        def control_state():
            real_now = datetime.now(SEOUL)
            now = story_now(clock.state, real_now)
            active = snapshots.get(replay.episode.episode_id)
            timeline = stages(active, now)
            upcoming = next((stage for stage in timeline if not stage["done"] and not stage["unreachable"]), None)
            seconds = None
            if upcoming and not upcoming["held"]:
                seconds = clock.seconds_until(datetime.fromisoformat(upcoming["at"]), real_now)
            detail = active.episode_detail(now) if active else None
            moment_list = plan_moments(active) if active and not (active.skipped or active.read_failure) else []
            selection = pending_order or default_scene
            return {
                "clock": {**clock_response(real_now), "rate": clock.rate_at(real_now),
                          "paused": not clock.state.rate,
                          "ramp_active": clock.state.ramp_until is not None and real_now < clock.state.ramp_until},
                "household": {"id": replay.household_id, "paused": replay.paused},
                "episode": ({
                    "id": detail.episode_id, "status": detail.status, "item_count": detail.item_count,
                    "shared_at": detail.shared_at,
                } if detail else None),
                "timeline": timeline, "next_stage": upcoming["id"] if upcoming else None,
                "seconds_until_next_stage": seconds,
                "moments": [entry for entry in moment_list if datetime.fromisoformat(entry["at"]) > now],
                "plans": rehearsal.versions(snapshots.values(), now),
                "cards": [
                    wire(snapshot.card) for snapshot in reversed(snapshots.values())
                    if snapshot.card and snapshot.published(now)
                ],
                "last": {key: traffic.last.get(key) for key in ("hub_pull", "app_card_poll", "shell_request")},
                "faults": [fault.entry() for fault in traffic.faults.values()],
                "active_case": rehearsal.active_case, "available_episodes": choices,
                "next_order": selection.episode_id if selection else None,
                "queued_next_order": pending_order.episode_id if pending_order else None,
                "next_pace": rehearsal.next_pace.model_dump() if rehearsal.next_pace else None,
                "realistic_seed": traffic.realistic_seed,
                "can_repeat": rehearsal.sample_source in orders,
                "can_capture": bool(
                    active and rehearsal.capture_episode == active.episode.episode_id
                    and now < active.quiet_end and not active.paused
                ),
                "sample_response": rehearsal.sample_response,
                "catalogue": rehearsal.catalogue(replay.household_id),
            }

        def change_pace(pace):
            try:
                schedule = pace.schedule()
                if pace.scope == "next":
                    rehearsal.next_pace = pace
                else:
                    if not snapshots or not replay.judgment_at or replay.published() or replay.read_failure:
                        raise ValueError("There is no current judgment in progress")
                    retime(replay, pace, schedule)
            except ValueError as exc:
                raise FixtureError(409, "invalid_request", str(exc)) from exc

        async def fixture_call(method, path, **kwargs):
            # Exercise the same multipart/JSON validation and fault middleware as the App.
            transport = httpx2.ASGITransport(app=app, client=("127.0.0.1", 0))
            async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                try:
                    reply = await client.request(method, path, headers={"Authorization": "Bearer fixture-control"}, **kwargs)
                except ConnectionDropped:
                    rehearsal.sample_response = {"status": None, "body": None}
                else:
                    rehearsal.sample_response = {"status": reply.status_code, "body": reply.json()}

        async def sample_share(action):
            if action == "repeat":
                source = rehearsal.sample_source
                if source not in orders:
                    raise FixtureError(409, "invalid_request", "Share a sample first")
            else:
                if action == "capture" and not control_state()["can_capture"]:
                    raise FixtureError(409, "invalid_request", "There is no armed second capture inside the quiet window")
                while True:
                    rehearsal.sample_serial += 1
                    source = f"fixture-sample-{rehearsal.sample_serial}"
                    if source not in orders:
                        break
                if pending_order is None and default_scene is None and action != "capture":
                    select_order(NextOrder(episode_id=episode_id))
                rehearsal.sample_source = source
            await fixture_call(
                "POST", "/v1/orders", data={"household_id": replay.household_id, "source_id": source},
                files=[("images", ("sample.png", SAMPLE_PNG, "image/png"))],
            )

        async def recorded_calendar():
            if not snapshots or not replay.calendar or not replay.published() or not replay.card or replay.card.starts_at:
                raise FixtureError(409, "invalid_request", "A published held card is required")
            await fixture_call("PUT", f"/v1/households/{replay.household_id}/calendar", json=wire(replay.calendar))

        def reset_episode(order):
            nonlocal replay
            reset = Replay(order.episode_id)
            reset.story_clock = clock
            reset.devices, reset.profile = replay.devices, replay.profile
            replay = reset
            snapshots.clear()
            historical_package_replays.clear()
            orders.clear()
            rehearsal.active_case = rehearsal.share_mode = rehearsal.capture_episode = None
            rehearsal.derive_next = rehearsal.resend_version = rehearsal.sample_response = None
            rehearsal.next_pace = None
            rehearsal.pulls.clear()
            rehearsal.acked_at.clear()
            shared_at = datetime.fromisoformat(replay.episode.shared_at).astimezone(SEOUL)
            clock.set(shared_at - timedelta(minutes=1), datetime.now(SEOUL))

        @app.get(CONTROL, dependencies=local, response_class=HTMLResponse)
        async def control_page():
            return HTMLResponse(Path(__file__).with_name("control.html").read_text(encoding="utf-8"),
                                headers={"Cache-Control": "no-store"})

        @app.get(CONTROL + "/state", dependencies=local)
        async def read_control_state():
            return JSONResponse(control_state(), headers={"Cache-Control": "no-store"})

        @app.get(CONTROL + "/log", dependencies=local)
        async def control_log(after: int = 0):
            return {"requests": [row for row in reversed(traffic.log) if row["id"] > after],
                    "last_id": traffic.serial}

        @app.post(CONTROL + "/clock", dependencies=local)
        async def control_clock(change: ClockAction):
            real_now = datetime.now(SEOUL)
            if change.action == "set" and change.at:
                clock.set(timestamp(change.at).astimezone(SEOUL), real_now)
            elif change.action == "advance" and change.at:
                advance_clock(timestamp(change.at).astimezone(SEOUL), real_now, change.over_seconds)
            elif change.action == "advance" and change.moment:
                move_to_moment(real_now, change.over_seconds, change.moment)
            elif change.action == "next":
                move_to_moment(real_now, change.over_seconds)
            elif change.action == "pause":
                clock.pause(real_now)
            elif change.action == "resume":
                clock.resume(real_now)
            elif change.action == "rate" and change.rate is not None:
                clock.set_rate(change.rate, real_now)
            else:
                raise FixtureError(422, "validation_error", "Specify at, moment or rate for this action")
            return control_state()

        @app.post(CONTROL + "/judgment", dependencies=local)
        async def control_judgment(pace: Pace):
            change_pace(pace)
            return control_state()

        @app.post(CONTROL + "/realistic", dependencies=local)
        async def control_realistic(change: Realistic):
            traffic.set_realistic(change.seed)
            if change.seed is not None:
                rehearsal.next_pace = None
            return control_state()

        @app.post(CONTROL + "/episode", dependencies=local)
        async def control_episode(change: EpisodeAction):
            if change.action in ("select", "reset"):
                order = change.episode_id or (pending_order and pending_order.episode_id) or next(
                    id_ for id_ in choices if replay.episode.episode_id.startswith(id_)
                )
                order = NextOrder(episode_id=order)
                select_order(order)
                if change.action == "reset":
                    reset_episode(order)
            elif change.action == "resume":
                apply_pause(False)
            elif change.action == "calendar":
                await recorded_calendar()
            else:
                await sample_share(change.action)
            return control_state()

        @app.post(CONTROL + "/fault", dependencies=local)
        async def control_fault(fault: Fault):
            traffic.faults[fault.group] = fault
            return control_state()

        @app.post(CONTROL + "/fault/{group}/clear", dependencies=local)
        async def clear_fault(group: Group):
            traffic.faults.pop(group, None)
            return control_state()

        @app.post(CONTROL + "/case", dependencies=local)
        async def control_case(change: CaseAction):
            case = CASES_BY_ID.get(change.id)
            if change.id is not None and not case:
                raise FixtureError(404, "not_found", "Unknown rehearsal case")
            if case and not case.entry(replay.household_id)["reproducible"]:
                raise FixtureError(409, "invalid_request", case.entry(replay.household_id)["needs"])
            action = case.action if case else {}
            plan_mode = action.get("plan")
            resend = None
            if plan_mode in ("equal", "lower"):
                version = replay.plan.plan_version
                prior = [
                    prev for prev in replay.plans if prev < version
                    and (replay.plan.plan_id, prev) in rehearsal.pulls
                ]
                if (replay.plan.plan_id, version) not in rehearsal.pulls or (plan_mode == "lower" and not prior):
                    raise FixtureError(409, "invalid_request", "The Hub must first pull the relevant plan versions")
                resend = replay.plan.plan_id, version if plan_mode == "equal" else max(prior)
            if "calendar" in action:
                await recorded_calendar()
            if "episode" in action:
                select_order(NextOrder(episode_id=action["episode"]))
            if any(key in action for key in ("pace", "hold", "release")):
                in_progress = snapshots and replay.judgment_at and not replay.published() and not replay.read_failure
                scope = "current" if "release" in action or (in_progress and not action.get("next")) else "next"
                preset = action.get("pace") or ("release" if "release" in action else "stuck")
                change_pace(Pace(preset=preset, scope=scope, hold=action.get("hold")))
            if "pause" in action:
                apply_pause(action["pause"])
            if "fault" in action:
                fault = Fault(**action["fault"])
                traffic.faults[fault.group] = fault
            rehearsal.share_mode = action.get("share_mode")
            rehearsal.capture_episode = None
            rehearsal.derive_next = plan_mode if plan_mode not in ("equal", "lower") else None
            rehearsal.resend_version = resend
            rehearsal.active_case = change.id
            return control_state()

    return app
