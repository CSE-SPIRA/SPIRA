"""Demo route (contracts/openapi/demo.yaml, spec §12.5): stage states and times of one judgment for the presenter
screen. Only with DEMO_MODE=1; otherwise every path here answers 404 as if it did not exist."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..db.engine import session_scope
from ..db.models import CalendarEvent, Card, DeviceList, Episode, Household, LlmCall, OrderItem, Plan, Task
from ..paths import SERVER_DIR
from ..pipeline.s5_cards import card_body
from ..pipeline.stage_times import wall
from ..settings import get_settings
from .auth import require_app
from .errors import ApiError

router = APIRouter(dependencies=[Depends(require_app)])

STAGES = ("s1", "s2", "s3", "s4", "s5")
LLM_STAGES = ("s1", "s3", "s4")


def _demo_only() -> None:
    if not get_settings().demo_mode:
        raise ApiError("not_found", "Not found.")


def _llm(s: Session, episode_id: str) -> dict[str, dict]:
    rows = s.execute(
        select(LlmCall.stage, func.count(), func.coalesce(func.sum(LlmCall.latency_ms), 0),
               func.coalesce(func.sum(LlmCall.input_tokens), 0), func.coalesce(func.sum(LlmCall.output_tokens), 0))
        .where(LlmCall.episode_id == episode_id, LlmCall.stage.in_(LLM_STAGES)).group_by(LlmCall.stage)).all()
    return {st: {"calls": int(n), "ms": int(ms), "input_tokens": int(i), "output_tokens": int(o)}
            for st, n, ms, i, o in rows}


def _failed_stage(ep: Episode) -> str | None:
    """Where the episode stopped early: s1 read nothing / every item masked ends after s1; s2 KB down."""
    if ep.status == "read_failed":
        return "s1"
    if (ep.error or {}).get("stage") == "s2":
        return "s2"
    return None


def trace_body(s: Session, ep: Episode, at: float | None, now: datetime | None = None) -> dict:
    times = ep.stage_times or {}
    start = clock.parse(times["received"]) if "received" in times else None
    elapsed = at if at is not None else ((now or wall()) - start).total_seconds() if start else None

    def offset(key: str) -> float | None:
        return round((clock.parse(times[key]) - start).total_seconds(), 3) if start and key in times else None

    failed = _failed_stage(ep)
    masked_only = ep.status == "judged" and (ep.intent or {}).get("none_reason") == "all_masked" and "s2" not in times
    llm = _llm(s, ep.id)
    stages, stopped, running_given = [], False, False
    for name in STAGES:
        done_s = offset(name)
        ended = name in times if start is None else done_s is not None and (at is None or done_s <= at)
        if start is None and name not in times:                     # stored before stage times: from the status
            ended = ep.stage == "done" or (ep.stage == "s2" and name in ("s1", "s2"))
        if stopped:
            state = "skipped"
        elif ended:
            state = "failed" if name == failed else "done"
            stopped = name == failed or (masked_only and name == "s1")
        else:
            s1_start = offset("s1_start")
            started = name != "s1" or (s1_start is not None and (at is None or s1_start <= at)) or start is None
            moving = at is not None or ep.stage != "done"
            state = "running" if started and moving and not running_given else "pending"
            running_given = True                                     # only the first unfinished stage can run
        stages.append({"name": name, "state": state,
                       "done_s": done_s if state in ("done", "failed") else None,
                       "llm": llm.get(name) if state == "done" and name in LLM_STAGES else None,
                       "result": _result(s, ep, name) if state in ("done", "failed") else None})
    return {
        "episode_id": ep.id, "status": ep.status, "mode": "live" if at is None else "replay", "at": at,
        "started_at": times.get("received"), "elapsed_s": round(elapsed, 3) if elapsed is not None else None,
        "finished": all(x["state"] in ("done", "failed", "skipped") for x in stages), "stages": stages,
    }


def _result(s: Session, ep: Episode, name: str) -> dict:
    """What the stage stored, as stored (no wording added, nothing recomputed). spec §12.5."""
    if name == "s1":
        rows = s.execute(select(OrderItem).where(OrderItem.episode_id == ep.id)).scalars().all()
        rows = sorted(rows, key=lambda r: int(r.id.rsplit("_", 1)[-1]) if r.id.rsplit("_", 1)[-1].isdigit() else 0)
        return {"items": [{"item_id": r.id, "name": None if r.masked else r.name, "type": None if r.masked else r.type,
                           "qty": r.qty, "attributes": list(r.attributes or []) if not r.masked else [],
                           "masked": r.masked} for r in rows],
                "error": (ep.error or {}).get("message") if ep.status == "read_failed" else None}
    if name == "s2":
        ctx = ep.context or {}
        fi = ctx.get("for_intent") or {}
        home = fi.get("this_home")
        kb = fi.get("kb_neighbors")
        return {"household_types": (home or {}).get("household_types"),
                "unusual_items": (home or {}).get("unusual_items"), "calendar": (home or {}).get("calendar"),
                "kb": None if kb is None else {
                    "similar_count": kb.get("similar_count"), "base_total": kb.get("base_total"),
                    "intent_counts": kb.get("intent_counts") or [], "note": kb.get("note")},
                "kb_search": ctx.get("kb_search"),
                "error": (ep.error or {}).get("message") if (ep.error or {}).get("stage") == "s2" else None}
    if name == "s3":
        intent = ep.intent or {}
        return {"bundles": [{k: b.get(k) for k in ("intent_id", "intent_text", "situation", "basis", "calendar_event_id",
                                                 "calendar_tags", "use_window")} for b in intent.get("bundles") or []],
                "none_reason": intent.get("none_reason"), "unbundled": intent.get("unbundled") or [],
                "error": intent.get("error")}
    if name == "s4":
        return ep.s4 or {}
    cards = s.execute(select(Card).where(Card.episode_id == ep.id, Card.archived.is_(False))
                      .order_by(Card.ordinal)).scalars().all()
    plan = s.execute(select(Plan.version).where(Plan.episode_id == ep.id).order_by(Plan.version.desc())
                     .limit(1)).scalar_one_or_none()
    dropped = s.execute(select(Task).where(Task.episode_id == ep.id, Task.drop_reason.is_not(None))
                        .order_by(Task.task_id)).scalars().all()
    return {"cards": [card_body(s, c) for c in cards], "plan_version": plan,
            "dropped": [{"task_id": d.task_id, "source": d.source, "line": d.line,
                         "item": (d.meta or {}).get("item"), "reason": d.drop_reason} for d in dropped]}


@router.get("/v1/demo/episodes/{episode_id}/trace", dependencies=[Depends(_demo_only)])
def get_trace(episode_id: str = Path(pattern=r"^ep_[0-9A-Za-z_]+$"),
              at: float | None = Query(None, ge=0)) -> dict:
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        if ep is None:
            raise ApiError("not_found", "Unknown episode.")
        return trace_body(s, ep, at)


@router.post("/v1/demo/households/{household_id}/reset", dependencies=[Depends(_demo_only)])
def reset_household(household_id: str = Path(pattern=r"^h_[0-9a-z]+$")) -> dict:
    """Write the demo home again from DEMO_HOME (spec §12.5): what the presenter put there on purpose stays
    (household types, devices, calendar re-based to now, past orders); test orders, tasks, cards, plans and memory
    rows go. The hub key stays, so a running hub keeps working. Do not press it while an order is being judged."""
    from ..dev.seed import HomeError, existing_hub_key_hash, load_home, park_replays, seed

    key_hash = existing_hub_key_hash(household_id)
    if key_hash is None:
        raise ApiError("not_found", "Unknown household.")
    path = SERVER_DIR / get_settings().demo_home
    from .. import demo_clock

    demo_clock.reset()                           # story clock back on wall time (§12.6); the calendar re-bases to it
    now = clock.now()
    try:
        home = load_home(path, now)
    except (HomeError, OSError) as e:
        raise ApiError("internal", f"Demo home not readable: {e}") from e
    home.household_id = household_id
    home.devices["household_id"] = household_id
    parked = park_replays(household_id)
    written = seed(home, now, hub_key_hash=key_hash)
    return {"replays_kept": len(parked),"household_id": household_id, "devices": written["devices"], "calendar": written["calendar"],
            "calendar_tagged": written["calendar_tagged"], "past_orders": written["past_orders"],
            "now": clock.iso(now)}


@router.post("/v1/demo/episodes/{episode_id}/keep", dependencies=[Depends(_demo_only)])
def keep_for_replay(body: dict | None = None, episode_id: str = Path(pattern=r"^ep_[0-9A-Za-z_]+$")) -> dict:
    """Mark a judged episode to keep for the replay (`{"keep": false}` undoes it). It survives the next reset."""
    keep = True if not body or "keep" not in body else body["keep"]
    if not isinstance(keep, bool):
        raise ApiError("validation_error", "keep must be true or false.")
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        if ep is None:
            raise ApiError("not_found", "Unknown episode.")
        if keep and not ep.judged:
            raise ApiError("invalid_request", "Only a judged episode can be kept.")
        ep.replay_kept = keep
        return {"episode_id": ep.id, "kept": keep}


@router.get("/v1/demo/households/{household_id}/replays", dependencies=[Depends(_demo_only)])
def list_replays(household_id: str = Path(pattern=r"^h_[0-9a-z]+$")) -> dict:
    """Episodes kept for the replay, newest first: still in the household or already parked in its archive."""
    from ..dev.seed import replay_archive

    with session_scope() as s:
        rows = s.execute(select(Episode).where(Episode.household_id.in_((household_id, replay_archive(household_id))),
                                               Episode.replay_kept.is_(True))
                         .order_by(Episode.received_at.desc())).scalars().all()
        out = []
        for ep in rows:
            times = ep.stage_times or {}
            start = clock.parse(times["received"]) if "received" in times else None
            end = clock.parse(times["s5"]) if "s5" in times else None
            out.append({"episode_id": ep.id, "started_at": times.get("received"),
                        "duration_s": round((end - start).total_seconds(), 3) if start and end else None,
                        "intents": [b["intent_id"] for b in (ep.intent or {}).get("bundles") or []],
                        "items": s.execute(select(func.count()).select_from(OrderItem)
                                           .where(OrderItem.episode_id == ep.id)).scalar(),
                        "parked": ep.household_id != household_id})
        return {"replays": out}


@router.get("/v1/demo/households/{household_id}/status", dependencies=[Depends(_demo_only)])
def household_status(household_id: str = Path(pattern=r"^h_[0-9a-z]+$")) -> dict:
    """What the Server already knows about the household before an order (the presenter's idle console): household
    types, devices by room, the order history and the coming calendar. Stored values only; event titles are never
    stored, so events show their id, tags and times."""
    now = clock.now()
    with session_scope() as s:
        household = s.get(Household, household_id)
        if household is None:
            raise ApiError("not_found", "Unknown household.")
        dl = s.get(DeviceList, household_id)
        rooms: dict[str, int] = {}
        for device in (dl.body or {}).get("devices", []) if dl else []:
            room = device.get("room") or "-"
            rooms[room] = rooms.get(room, 0) + 1
        episodes = s.execute(select(Episode).where(Episode.household_id == household_id)
                             .order_by(Episode.shared_at.desc())).scalars().all()
        latest = None
        if episodes:
            items = s.execute(select(OrderItem.type).where(OrderItem.episode_id == episodes[0].id,
                                                           OrderItem.masked.is_(False))
                              .order_by(OrderItem.id)).scalars().all()
            latest = {"episode_id": episodes[0].id, "shared_at": clock.iso(episodes[0].shared_at),
                      "status": episodes[0].status, "items": [i for i in items if i]}
        events = s.execute(select(CalendarEvent).where(CalendarEvent.household_id == household_id,
                                                       CalendarEvent.end >= now)
                           .order_by(CalendarEvent.start)).scalars().all()
        return {
            "household_id": household_id, "household_types": list(household.household_types or []),
            "devices": {"count": sum(rooms.values()), "rooms": rooms},
            "orders": {"count": len(episodes), "latest": latest},
            "calendar": [{"id": e.id, "start": clock.iso(e.start), "end": clock.iso(e.end), "tags": list(e.tags or []),
                          "tagged": e.tagged} for e in events],
            "now": clock.iso(now),
        }
