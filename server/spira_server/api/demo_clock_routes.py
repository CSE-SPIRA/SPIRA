"""Demo story clock and moments (contracts/openapi/demo.yaml, spec §12.6). DEMO_MODE=1 only, else 404.

`GET /v1/demo/clock` has no auth so the Hub can follow it (it polls with no headers); every write and the moments
need the app token (the demo shell adds it)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock, demo_clock
from ..config import get_config
from ..db.engine import session_scope
from ..db.models import Card, Episode, Plan, Task, Window
from ..settings import get_settings
from .auth import require_app
from .errors import ApiError

router = APIRouter()

EPISODE = r"^ep_[0-9A-Za-z_]+$"
QUIET_END = "judgment.quiet_end"
LEAD_S = 20                      # a time moment is reached 20 s early so the Hub has pulled and is ready


def _demo_only() -> None:
    if not get_settings().demo_mode:
        raise ApiError("not_found", "Not found.")


def _over_seconds(body: dict) -> float:
    value = body.get("over_seconds", 6)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 60:
        raise ApiError("validation_error", "over_seconds must be 1–60.", {"path": "over_seconds"})
    return float(value)


def _body(raw: dict | None, allowed: set[str]) -> dict:
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ApiError("validation_error", "Body must be an object.", {"path": "(root)"})
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ApiError("validation_error", f"Unknown field {extra[0]}.", {"path": extra[0]})
    return raw


@router.get("/v1/demo/clock", dependencies=[Depends(_demo_only)])
def get_clock() -> dict:
    return demo_clock.get().body()


@router.post("/v1/demo/clock", dependencies=[Depends(_demo_only), Depends(require_app)])
def post_clock(raw: dict | None = None) -> dict:
    body = _body(raw, {"advance_to", "over_seconds"})
    if not isinstance(body.get("advance_to"), str):
        raise ApiError("validation_error", "advance_to is required.", {"path": "advance_to"})
    try:
        target = clock.parse(body["advance_to"])
    except ValueError:
        raise ApiError("validation_error", "advance_to must be an ISO time with offset.",
                       {"path": "advance_to"}) from None
    over = _over_seconds(body)
    try:
        return demo_clock.get().advance(target, over)
    except ValueError as e:
        raise ApiError("invalid_request", str(e)) from None


@router.get("/v1/demo/moments", dependencies=[Depends(_demo_only), Depends(require_app)])
def get_moments(episode_id: str | None = Query(None, pattern=EPISODE)) -> list[dict]:
    if episode_id is None:
        return []
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        if ep is None:
            raise ApiError("not_found", "Unknown episode.")
        return moments(s, ep)


@router.post("/v1/demo/clock/next", dependencies=[Depends(_demo_only), Depends(require_app)])
def next_moment(raw: dict | None = None, episode_id: str = Query(..., pattern=EPISODE)) -> dict:
    over = _over_seconds(_body(raw, {"over_seconds"}))
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        if ep is None:
            raise ApiError("not_found", "Unknown episode.")
        found = moments(s, ep)
    story = demo_clock.get()
    now = story.now()
    for moment in found:
        at = clock.parse(moment["at"])
        target = at - timedelta(seconds=LEAD_S) if moment["kind"] == "time" and moment["event"] != QUIET_END else at
        if target > now + timedelta(seconds=1):
            story.advance(target, over)
            return moment
    raise ApiError("not_found", "No story moments remain")


def moments(s: Session, ep: Episode) -> list[dict]:
    """Moments of one episode, from its latest plan version and its cards (spec §12.6), in time order:
    time triggers (tasks at the same time share one), guest-window openings (their own moment, event
    guest_arrived), each card's schedule end
    (`event_end`, what the presenter acts out) and, before S1 ran, the quiet-window end."""
    cfg = get_config()
    out: dict[str, dict] = {}

    def add(at: datetime, kind: str, label: str, event: str | None, task_id: str | None, key: str) -> None:
        iso = clock.iso(at)
        entry = out.get(key)
        if entry is None:
            entry = out[key] = {"id": f"{key.split(':')[0]}:{task_id or event}", "at": iso, "kind": kind,
                                "label": label,
                                "task_ids": [], "event": event, "episode_id": ep.id}
        elif task_id and label not in entry["label"].split(" · "):
            entry["label"] += f" · {label}"
        if task_id:
            entry["task_ids"].append(task_id)

    plan = s.get(Plan, (ep.id, ep.plan_version)) if ep.plan_version else None
    lines = {t.task_id: t.line for t in s.execute(select(Task).where(Task.episode_id == ep.id)).scalars()}
    for task in (plan.body["tasks"] if plan else []):
        trigger = task.get("trigger") or {}
        label = lines.get(task["task_id"]) or task["task_id"]
        if "time" in trigger:
            at = clock.parse(trigger["time"])
            add(at, "time", label, None, task["task_id"], f"time:{clock.iso(at)}")
        elif trigger.get("event") == "guest_arrived" and trigger.get("window"):
            at = clock.parse(trigger["window"]["from"])
            add(at, "time", "손님 맞이", "guest_arrived", task["task_id"], f"guest:{clock.iso(at)}")
    fallback = timedelta(minutes=cfg.numbers.end_fallback_min)
    whens = (ep.s4 or {}).get("whens") or {}
    bundles = (ep.intent or {}).get("bundles") or []
    for card, window in s.execute(select(Card, Window).join(Window, Window.card_id == Card.id)
                                  .where(Card.episode_id == ep.id, Card.archived.is_(False),
                                         Card.stopped.is_(False))).all():
        if window.status == "closed" or card.starts_at is None:
            continue
        end = _schedule_end(whens.get(str(card.bundle_index)), bundles, card.bundle_index)
        if end is None and window.end_due is not None:
            end = window.end_due - fallback
        if end is not None:
            add(end, "event", "일정 끝", "event_end", None, f"event:{clock.iso(end)}")
    if ep.quiet_due is not None and ep.status == "received":
        add(ep.quiet_due, "time", "같은 주문을 기다리는 시간 끝", QUIET_END, None, "quiet")
    return sorted(out.values(), key=lambda m: (clock.parse(m["at"]), m["kind"] != "time"))


def _schedule_end(when: dict | None, bundles: list[dict], index: int) -> datetime | None:
    """The schedule end S4 used (episodes.s4 whens), else the bundle's use window end."""
    if when and when.get("end"):
        return clock.parse(when["end"])
    window = (bundles[index].get("use_window") if index < len(bundles) else None) or {}
    return clock.parse(window["end"]) if window.get("end") else None
