"""HTTP transport for the non-inference fixture replay."""

import logging
from datetime import datetime

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from spira_contracts.ack import Ack
from spira_contracts.calendar import Calendar
from spira_contracts.calendar_response import CalendarResponse
from spira_contracts.cards_response import CardsResponse
from spira_contracts.common import EpisodeStatus
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
from spira_contracts.order_accepted import OrderAccepted
from spira_contracts.order_edit import OrderEdit
from spira_contracts.pause import Pause
from spira_contracts.plan_pull import PlanPull
from spira_contracts.profile import Profile
from spira_contracts.rationale import Rationale
from spira_contracts.reaction import Reaction
from spira_contracts.validate import ContractError, validate
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from .replay import Replay, valid_household_types, wire

LABEL = "SPIRA fixture - non-inference test support"
LABEL_HEADER = "X-SPIRA-Fixture"
logger = logging.getLogger("uvicorn.error")


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


def create_app(episode_id: str = "ep_9031") -> FastAPI:
    replay = Replay(episode_id)
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
        if requested_episode != episode_id:
            raise FixtureError(
                404, "not_found", "Episode is outside the selected fixture"
            )

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
        replay.put_calendar(calendar)
        return response(CalendarResponse(accepted=len(calendar.events)), 202)

    @app.post("/v1/households/{household_id}/pause", dependencies=app_auth)
    async def put_pause(household_id: str, request: Request):
        require_household(household_id)
        pause = await read_body(request, Pause)
        replay.pause(pause.paused)
        return response(Pause(household_id=household_id, paused=replay.paused))

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
        episodes = []
        episode = replay.episode
        if before is None or datetime.fromisoformat(episode.shared_at) < before:
            episodes.append(
                EpisodeSummary(
                    episode_id=episode_id,
                    shared_at=episode.shared_at,
                    status=episode.status,
                    item_count=episode.item_count,
                    card_ids=episode.card_ids,
                )
            )
        return response(EpisodeList(episodes=episodes, next_before=None))

    @app.get("/v1/households/{household_id}/cards", dependencies=app_auth)
    async def get_cards(household_id: str, request: Request):
        require_household(household_id)
        since = timestamp(request.query_params.get("since"))
        card = replay.card
        if since is None:
            cards = [card] if card and not replay.finished and not card.stopped else []
        else:
            cards = (
                [card]
                if card and datetime.fromisoformat(card.updated_at) > since
                else []
            )
        return response(
            CardsResponse(cards=cards, server_time=replay.clock.isoformat())
        )

    @app.get("/v1/households/{household_id}/memory", dependencies=app_auth)
    async def get_memory(household_id: str):
        require_household(household_id)
        return response(replay.memory)

    @app.delete("/v1/households/{household_id}/memory/{case_id}", dependencies=app_auth)
    async def forget_case(household_id: str, case_id: str):
        require_household(household_id)
        for intent in replay.memory.intents:
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
                replay.memory.intents = [
                    entry for entry in replay.memory.intents if entry.episodes
                ]
                return Response(status_code=204)
        raise FixtureError(404, "not_found", "No such case in the replayed memory")

    @app.post("/v1/orders", dependencies=app_auth)
    async def post_order(request: Request):
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
        duplicate = source_id in replay.source_ids
        if source_id is not None:
            replay.source_ids.add(source_id)
        status = EpisodeStatus.PAUSED_SKIP if replay.paused else EpisodeStatus.RECEIVED
        return response(
            OrderAccepted(episode_id=episode_id, status=status),
            200 if duplicate else 202,
        )

    @app.get("/v1/episodes/{episode_id}", dependencies=app_auth)
    async def get_episode(episode_id: str):
        require_episode(episode_id)
        return response(replay.episode)

    @app.put("/v1/episodes/{episode_id}/order", dependencies=app_auth)
    async def edit_order(episode_id: str, request: Request):
        require_episode(episode_id)
        await read_body(request, OrderEdit)
        status = EpisodeStatus.PAUSED_SKIP if replay.paused else EpisodeStatus.RECEIVED
        return response(OrderAccepted(episode_id=episode_id, status=status), 202)

    @app.get("/v1/episodes/{episode_id}/rationale", dependencies=app_auth)
    async def get_rationale(episode_id: str):
        require_episode(episode_id)
        rationale = (
            replay.load(Rationale, "rationale.json") if replay.finished else None
        )
        if rationale is None:
            raise FixtureError(
                404, "not_found", "No rationale snapshot at this fixture step"
            )
        return response(rationale)

    @app.post("/v1/cards/{card_id}/reactions", dependencies=app_auth)
    async def react(card_id: str, request: Request):
        if not replay.card or replay.card.card_id != card_id or replay.finished:
            raise FixtureError(
                404, "not_found", "No open card with this ID in the fixture"
            )
        reaction = await read_body(request, Reaction)
        try:
            return response(replay.react(reaction))
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
        return response(
            PlanPull(
                household_id=replay.household_id,
                paused=replay.paused,
                devices_revision=replay.devices.revision,
                plans=[] if replay.finished else [replay.plan],
            )
        )

    @app.post("/v1/hub/plans/{plan_id}/ack", dependencies=hub_auth)
    async def ack_plan(plan_id: str, request: Request):
        require_episode(plan_id)
        ack = await read_body(request, Ack)
        replay.acks[ack.plan_version] = ack
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
                if event.event_id not in replay.events:
                    if event.source != "hub" and event.source not in device_ids:
                        raise ContractError("Unknown fixture device")
                    replay.events[event.event_id] = raw
                    changed = replay.release_package(event) or changed
                accepted.append(event.event_id)
            except (ContractError, ValidationError):
                event_id = raw.get("event_id") if isinstance(raw, dict) else None
                rejected.append(
                    RejectedItem(
                        event_id=event_id if isinstance(event_id, str) else "",
                        code="validation_error",
                        message=f"{LABEL}. Invalid event or unknown fixture device",
                    )
                )
        changed = replay.finish_if_replayed() or changed
        return response(
            EventResponse(accepted=accepted, rejected=rejected, plans_changed=changed)
        )

    @app.post("/v1/hub/executions", dependencies=hub_auth)
    async def post_execution(request: Request):
        receipts = replay.receipts["executions"]
        result = await read_body(request, ExecutionResult, receipts=receipts)
        require_episode(result.root.plan_id)
        result_id = result.root.result_id
        duplicate = result_id in replay.results
        if not duplicate:
            replay.results[result_id] = result
            replay.result_bodies[result_id] = receipts[-1]
            replay.finish_if_replayed()
        return response(ExecutionResponse(duplicate=duplicate))

    return app
