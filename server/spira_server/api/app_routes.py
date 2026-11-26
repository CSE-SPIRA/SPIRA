"""App routes (contracts/openapi/app.yaml): households, profile, calendar, cards, reactions, orders, the episode list,
one episode and its rationale. Pause, order edit and memory come with the rest of S6."""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Path, Query, UploadFile
from fastapi.responses import JSONResponse
from spira_contracts.calendar import Calendar
from spira_contracts.household_create import HouseholdCreate
from spira_contracts.profile import Profile
from spira_contracts.reaction import Reaction
from sqlalchemy import func, select

from .. import clock
from ..config import get_config
from ..db.engine import lock_household, next_id, session_scope
from ..db.models import Card, Episode, Household, OrderItem
from ..kb.household import check_types
from ..pipeline import s1_extract, s2_calendar, s5_reactions
from ..pipeline.s5_cards import card_body
from ..store.images import image_kind
from .auth import new_hub_key, require_app
from .episode_views import episode_body, rationale_body
from .bodies import body
from .errors import ApiError

router = APIRouter(dependencies=[Depends(require_app)])

HOUSEHOLD = r"^h_[0-9a-z]+$"
EPISODE = r"^ep_[0-9A-Za-z_]+$"


def _types(types: list[str]) -> None:
    reason = check_types(types)
    if reason:
        raise ApiError("household_types_invalid", reason, {"path": "household_types"})


def _time(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    try:
        return clock.parse(value.replace(" ", "+"))      # a '+' left unencoded in the query arrives as a space
    except ValueError:
        raise ApiError("validation_error", f"{name} needs ISO 8601 with offset.", {"path": name}) from None


# ------------------------------------------------------------------------------------------------ households

@router.post("/v1/households")
def post_household(data: dict = body(HouseholdCreate, "household_create.json")) -> JSONResponse:
    _types(data["household_types"])
    key, digest = new_hub_key()
    now = clock.now()
    with session_scope() as s:
        hid = next_id(s, "h", "household_id_seq")
        s.add(Household(id=hid, household_types=data["household_types"], paused=False, hub_key_hash=digest,
                        created_at=now, updated_at=now))
    return JSONResponse({"household_id": hid, "hub_api_key": key}, status_code=201)


@router.put("/v1/households/{household_id}/profile")
def put_profile(household_id: str = Path(pattern=HOUSEHOLD),
                data: dict = body(Profile, "profile.json")) -> dict:
    _types(data["household_types"])
    with session_scope() as s:
        h = lock_household(s, household_id)
        if h is None:
            raise ApiError("not_found", "Unknown household.")
        h.household_types, h.updated_at = data["household_types"], clock.now()    # later orders only
    return {"household_id": household_id, "household_types": data["household_types"]}


@router.put("/v1/households/{household_id}/calendar")
def put_calendar(background: BackgroundTasks, household_id: str = Path(pattern=HOUSEHOLD),
                 data: dict = body(Calendar, "calendar.json")) -> JSONResponse:
    events = [s2_calendar.CalendarInput(**e) for e in data["events"]]
    try:
        accepted = s2_calendar.receive_calendar(household_id, events)
    except LookupError:
        raise ApiError("not_found", "Unknown household.") from None
    background.add_task(s2_calendar.tag_events, accepted)               # titles stay in this task's memory only
    return JSONResponse({"accepted": accepted.accepted}, status_code=202)


@router.get("/v1/households/{household_id}/cards")
def get_cards(household_id: str = Path(pattern=HOUSEHOLD), since: str | None = Query(None)) -> dict:
    after = _time(since, "since")
    with session_scope() as s:
        if lock_household(s, household_id, shared=True) is None:     # no card write commits around server_time
            raise ApiError("not_found", "Unknown household.")
        now = clock.now()
        q = select(Card).join(Episode, Episode.id == Card.episode_id).where(Episode.household_id == household_id)
        if after is not None:
            q = q.where(Card.updated_at > after)                        # archived cards come once more, then never
        else:
            q = q.where(Card.archived.is_(False), Episode.status != "closed")
        cards = [card_body(s, c, now) for c in s.execute(q.order_by(Card.seq)).scalars()]
    return {"cards": cards, "server_time": clock.iso(now)}


@router.post("/v1/cards/{card_id}/reactions")
def post_reaction(card_id: str = Path(pattern=r"^nc_[0-9]+$"), data: dict = body(Reaction, "reaction.json")) -> dict:
    try:
        return s5_reactions.react(card_id, data["reaction"], data.get("task_id"))
    except s5_reactions.ReactionError as error:
        raise ApiError(error.code, str(error)) from None


# ---------------------------------------------------------------------------------------------------- orders

@router.post("/v1/orders")
async def post_orders(
    household_id: str = Form(...),
    images: list[UploadFile] | None = File(None),
    shared_at: str | None = Form(None),
    source_id: str | None = Form(None),
) -> JSONResponse:
    if not re.match(HOUSEHOLD, household_id):
        raise ApiError("validation_error", "household_id has the wrong format.", {"path": "household_id"})
    when = None
    if shared_at:
        try:
            when = clock.parse(shared_at)
        except ValueError:
            raise ApiError("validation_error", "shared_at needs ISO 8601 with offset.", {"path": "shared_at"}) from None

    n = get_config().numbers
    files = images or []
    if not 1 <= len(files) <= n.images_per_request:
        raise ApiError("invalid_image", f"Send 1 to {n.images_per_request} images.")
    payloads = []
    for f in files:
        data = await f.read()
        if len(data) > n.image_max_mb * 1024 * 1024:
            raise ApiError("invalid_image", f"Each image must be {n.image_max_mb} MB or smaller.")
        if image_kind(data) is None:
            raise ApiError("invalid_image", "Images must be jpg or png.")
        payloads.append(data)

    try:
        accepted = s1_extract.receive_capture(household_id, payloads, when, source_id or None)
    except s1_extract.UnknownHousehold:
        raise ApiError("not_found", "Unknown household.") from None
    out = {"episode_id": accepted.episode_id, "status": accepted.status}
    return JSONResponse(out, status_code=200 if accepted.duplicate else 202)


# -------------------------------------------------------------------------------------------------- episodes

@router.get("/v1/episodes/{episode_id}")
def get_episode(episode_id: str = Path(pattern=EPISODE)) -> dict:
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        if ep is None:
            raise ApiError("not_found", "Unknown episode.")
        return episode_body(s, ep)


@router.get("/v1/episodes/{episode_id}/rationale")
def get_rationale(episode_id: str = Path(pattern=EPISODE)) -> dict:
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        if ep is None:
            raise ApiError("not_found", "Unknown episode.")
        body = rationale_body(s, ep)
        if body is None:
            raise ApiError("not_found", "No rationale yet: S2 has not stored its context.")
        return body


@router.get("/v1/households/{household_id}/episodes")
def get_episodes(household_id: str = Path(pattern=HOUSEHOLD), limit: int = Query(20, ge=1, le=100),
                 before: str | None = Query(None)) -> dict:
    """Order history, newest first by shared_at (§12.2); next_before pages to older ones."""
    cursor = _time(before, "before")
    with session_scope() as s:
        if s.get(Household, household_id) is None:
            raise ApiError("not_found", "Unknown household.")
        q = select(Episode).where(Episode.household_id == household_id)
        if cursor is not None:
            q = q.where(Episode.shared_at < cursor)
        rows = s.execute(q.order_by(Episode.shared_at.desc(), Episode.id.desc()).limit(limit + 1)).scalars().all()
        page = rows[:limit]
        counts = dict(s.execute(select(OrderItem.episode_id, func.count()).where(
            OrderItem.episode_id.in_([e.id for e in page])).group_by(OrderItem.episode_id)).all())
        cards: dict[str, list[str]] = {}
        for c in s.execute(select(Card).where(Card.episode_id.in_([e.id for e in page]), Card.archived.is_(False))
                           .order_by(Card.ordinal)).scalars():
            cards.setdefault(c.episode_id, []).append(c.id)
        return {"episodes": [{"episode_id": e.id, "shared_at": clock.iso(e.shared_at), "status": e.status,
                              "item_count": counts.get(e.id, 0), "card_ids": cards.get(e.id, [])[:2]} for e in page],
                "next_before": clock.iso(page[-1].shared_at) if len(rows) > limit else None}
