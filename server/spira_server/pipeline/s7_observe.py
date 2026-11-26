"""S7 observation and this-home memory (spec §13), and the end jobs of §11.8. No LLM.

    on_start(s, task, at)                      first confirmed start of a situation task -> window open
    on_event_end(s, household_id, at, now)     an observed event_end closes the windows that contain it
    end_tasks(now) / close_windows(now) / close_episodes(now)    scheduled jobs (§2.3), safe to run twice
    memory_body(household_id, now)             GET /v1/households/{hid}/memory (§13.5)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_config
from ..db.engine import lock_household, session_scope
from ..db.models import Card, CardLine, Case, DeviceList, Episode, Event, Execution, Household, OrderItem, Task, Window
from ..kb.embedding import embed_basket
from ..kb.lists import get_lists
from .s4_tasks import action_key, catalog_from
from .s6_hub import refresh_task_lines, started

log = logging.getLogger(__name__)

RESTORE_WAIT = timedelta(hours=24)
PER_ITEM_WAIT = timedelta(days=14)


# ------------------------------------------------------------------------------------------------ windows

def on_start(s: Session, task: Task, at: datetime) -> None:
    window = s.execute(select(Window).where(Window.card_id == task.card_id)).scalar_one_or_none()
    if window is not None and window.status == "pending":
        window.status, window.start_at = "open", at


def _bounds(window: Window, cfg) -> tuple[datetime | None, datetime | None]:
    """[scheduled_start − guest_window_before_min, end_due] (§13.1 linking)."""
    if window.scheduled_start is None:
        return window.start_at, window.end_due
    return window.scheduled_start - timedelta(minutes=cfg.numbers.guest_window_before_min), window.end_due


def on_event_end(s: Session, household_id: str, at: datetime, now: datetime) -> None:
    rows = s.execute(select(Window).join(Episode, Episode.id == Window.episode_id)
                     .where(Episode.household_id == household_id, Window.status != "closed")).scalars().all()
    for window in rows:
        lo, hi = window.scheduled_start, window.end_due
        if lo is None or hi is None or not lo <= at <= hi:
            continue
        if window.status == "pending":
            window.status, window.start_at = "open", window.scheduled_start
        close_window(s, window, at, "event_end", now)


def close_window(s: Session, window: Window, at: datetime, reason: str, now: datetime) -> None:
    """Verdict (§13.3), task feedback (§13.4) and the memory row (§13.5) in the caller's transaction."""
    cfg = get_config()
    card = s.get(Card, window.card_id)
    ep = s.get(Episode, window.episode_id)
    window.status, window.end_at, window.end_reason = "closed", at, reason
    if window.start_at is None:
        window.start_at = window.scheduled_start
    lines = s.execute(select(CardLine, Task).join(Task, (Task.task_id == CardLine.task_id)
                                                  & (Task.episode_id == ep.id))
                      .where(CardLine.card_id == card.id).order_by(CardLine.position)).all()
    dl = s.get(DeviceList, ep.household_id)
    catalog = catalog_from(dl.body if dl else None)
    lo, hi = _bounds(window, cfg)
    hi = at
    events = s.execute(select(Event).where(Event.household_id == ep.household_id, Event.at <= at)
                       .order_by(Event.at)).scalars().all()

    def inside(ev: Event) -> bool:
        return (lo is None or ev.at >= lo) and ev.at <= hi

    signals = []
    for line, task in lines:
        if not line.checked:
            continue
        devices = {a["device"]: (catalog.get(a["device"]) if catalog else None) for a in task.actions}
        if task.way == "standby":
            for dev_id, dev in devices.items():
                kind = f"{dev.type}.started" if dev else None
                if any(ev.type == kind and ev.source == dev_id and (ev.payload or {}).get("by") == "user"
                       and inside(ev) for ev in events):
                    signals.append({"task_id": task.task_id, "signal": kind})
        elif task.way == "run" and "event" in (task.trigger or {}):
            name = task.trigger["event"]
            if any(ev.type == name and inside(ev) for ev in events):
                signals.append({"task_id": task.task_id, "signal": name})
    if card.stopped:
        verdict = "stopped"
    elif signals:
        verdict = "match"
    else:
        verdict = "unconfirmed"
    feedback = [_feedback(s, line, task, window, catalog, events, at) for line, task in lines]
    window.verdict, window.task_feedback = verdict, feedback
    window.checks = {"signals": signals}
    for _, task in lines:
        refresh_task_lines(s, task, now)                 # user_changed stops counting at the close
    _write_memory(s, window, card, ep, lines, catalog)


def _keys(task: Task, catalog) -> list[list[str]]:
    out = []
    for a in task.actions:
        dev = catalog.get(a["device"]) if catalog else None
        out.append(list(action_key(dev, a["cmd"])) if dev else [a["device"], a["cmd"]])
    return out


def _feedback(s: Session, line: CardLine, task: Task, window: Window, catalog, events: list[Event],
              at: datetime) -> dict:
    fb = {"task_id": task.task_id, "actions": _keys(task, catalog)}
    if not line.checked:
        fb["user"] = "off"
        fb["when"] = "during_run" if started(task) else "before_run"
        if line.checked_changed_at is not None:
            fb["at"] = line.checked_changed_at.astimezone(clock.KST).date().isoformat()
        return fb
    devices = {a["device"] for a in task.actions}
    changes = []
    if task.started_at is not None:
        base = window.scheduled_start or window.start_at
        for ev in events:
            if (ev.source in devices and ev.type.endswith(".changed") and (ev.payload or {}).get("by") == "user"
                    and task.started_at < ev.at <= at):
                dev = catalog.get(ev.source) if catalog else None
                changes.append({"device_type": dev.type if dev else ev.source,
                                "property": (ev.payload or {}).get("property"), "to": (ev.payload or {}).get("to"),
                                "after_start_minutes": int((ev.at - base).total_seconds() // 60) if base else 0})
    skipped = any(i.get("status") == "skipped_user_changed"
                  for r in s.execute(select(Execution).where(Execution.plan_id == task.episode_id,
                                                             Execution.task_id == task.task_id,
                                                             Execution.kind == "restore")).scalars()
                  for i in r.body.get("items", []))
    if changes or skipped:
        fb["user"] = "changed"
        fb["changes"] = changes
    else:
        fb["user"] = "kept"
    return fb


def _write_memory(s: Session, window: Window, card: Card, ep: Episode, lines, catalog) -> None:
    bundles = (ep.intent or {}).get("bundles") or []
    bundle = bundles[card.bundle_index] if card.bundle_index < len(bundles) else None
    if not lines or bundle is None or bundle.get("intent_id") == "unclassified":
        window.memory = "ineligible"
        return
    case_id = f"home_{ep.household_id}_{ep.id}_{card.ordinal}"
    if s.get(Case, case_id) is not None:
        window.memory = "written"
        return
    names = s.execute(select(OrderItem.type).where(OrderItem.episode_id == ep.id, OrderItem.masked.is_(False),
                                                   OrderItem.type.is_not(None))).scalars().all()
    items = sorted(set(names))
    executed = (window.start_at or window.scheduled_start or window.end_at).astimezone(clock.KST)
    household = s.get(Household, ep.household_id)
    try:
        emb = embed_basket(items)
    except Exception:                                     # retried by close_windows (§13.5)
        log.exception("memory embedding failed for %s", case_id)
        window.memory = "pending"
        return
    s.add(Case(case_id=case_id, source="this_home", items=items, intent_id=bundle["intent_id"],
               intent_text=bundle.get("intent_text") or bundle.get("sentence"), situation=bundle.get("situation") or {},
               when={"weekday": clock.weekday_ko(executed), "calendar_tags": list(bundle.get("calendar_tags") or []),
                     "executed_at": clock.iso(executed)},
               household={"types": list(household.household_types or [])}, basket_emb=emb, kb_version=None,
               household_id=ep.household_id,
               home_did=[{"task_id": t.task_id, "line": t.line or "", "way": t.way, "actions": _keys(t, catalog),
                          "ran": t.started_at is not None} for _, t in lines],
               verdict=window.verdict, task_feedback=window.task_feedback))
    window.memory = "written"


# ---------------------------------------------------------------------------------------------- end jobs

def _end_due(task: Task, s: Session, cfg) -> tuple[datetime | None, bool]:
    """(time the task ends, never fired?) from its end rule (§11.8); None = not yet known."""
    end, trig, meta = task.end or {}, task.trigger or {}, task.meta or {}
    fallback = timedelta(minutes=cfg.numbers.end_fallback_min)
    has_run = s.execute(select(Execution.result_id).where(Execution.plan_id == task.episode_id,
                                                          Execution.task_id == task.task_id,
                                                          Execution.kind == "run").limit(1)).first() is not None
    if meta.get("end_seen_at"):
        return clock.parse(meta["end_seen_at"]), not has_run and not started(task)
    candidates = []
    if end.get("time"):
        candidates.append(clock.parse(end["time"]))
    if end.get("or_time"):
        candidates.append(clock.parse(end["or_time"]))
    fired_at = None
    if "time" in trig:
        fired_at = clock.parse(trig["time"])
    elif trig.get("released") and trig.get("at"):
        fired_at = clock.parse(trig["at"])
    elif task.started_at is not None:
        fired_at = task.started_at
    if end.get("or_after") and fired_at is not None:
        candidates.append(fired_at + clock.parse_duration(end["or_after"]))
    if not has_run and not started(task):
        if trig.get("window") and trig.get("event") != "package.brought_in":
            candidates.append(clock.parse(trig["window"]["to"]))
            return min(candidates), True
        if "time" in trig:
            candidates.append(clock.parse(trig["time"]) + fallback)
            return min(candidates), True
        if trig.get("event") == "package.brought_in" and not trig.get("released"):
            return task.created_at + PER_ITEM_WAIT if task.created_at else None, True
    return (min(candidates) if candidates else None), False


def end_tasks(now: datetime | None = None) -> int:
    """Set `ended` on live tasks whose end came (§11.8). A task that must restore waits for its restore result
    (24 h, then restore_failed). Returns how many tasks ended."""
    cfg = get_config()
    ended = 0
    with session_scope() as s:
        households = s.execute(select(Episode.household_id).join(Task, Task.episode_id == Episode.id)
                               .where(Task.status == "live").distinct()).scalars().all()
    for hid in sorted(households):
        with session_scope() as s:
            lock_household(s, hid)
            now_ = now or clock.now()
            tasks = s.execute(select(Task).join(Episode, Episode.id == Task.episode_id)
                              .where(Episode.household_id == hid, Task.status == "live")
                              .order_by(Task.episode_id, Task.task_id)).scalars().all()
            for task in tasks:
                due, never = _end_due(task, s, cfg)
                if due is None or due > now_:
                    continue
                must_restore = started(task) and bool((task.end or {}).get("restore"))
                if must_restore:
                    if due + RESTORE_WAIT > now_:
                        continue                            # restore result still to come
                    task.meta = {**(task.meta or {}), "restore_timeout": True}
                if never:
                    task.meta = {**(task.meta or {}), "never_fired": True}
                task.status, task.ended_at = "ended", due
                refresh_task_lines(s, task, now_)
                ended += 1
    return ended


def close_windows(now: datetime | None = None) -> int:
    """Open windows at their scheduled start, close them by §13.1, retry pending memory rows. Returns closes."""
    closed = 0
    with session_scope() as s:
        households = s.execute(select(Episode.household_id).join(Window, Window.episode_id == Episode.id)
                               .where((Window.status != "closed") | (Window.memory == "pending")).distinct()
                               ).scalars().all()
    for hid in sorted(households):
        with session_scope() as s:
            lock_household(s, hid)
            now_ = now or clock.now()
            rows = s.execute(select(Window).join(Episode, Episode.id == Window.episode_id)
                             .where(Episode.household_id == hid).order_by(Window.id)).scalars().all()
            for window in rows:
                card = s.get(Card, window.card_id)
                if window.status == "closed":
                    if window.memory == "pending":
                        ep = s.get(Episode, window.episode_id)
                        lines = s.execute(select(CardLine, Task).join(
                            Task, (Task.task_id == CardLine.task_id) & (Task.episode_id == ep.id))
                            .where(CardLine.card_id == card.id).order_by(CardLine.position)).all()
                        dl = s.get(DeviceList, ep.household_id)
                        _write_memory(s, window, card, ep, lines, catalog_from(dl.body if dl else None))
                    continue
                tasks = s.execute(select(Task).where(Task.episode_id == window.episode_id,
                                                     Task.card_id == card.id)).scalars().all()
                if window.status == "pending" and window.scheduled_start is not None \
                        and window.scheduled_start <= now_:
                    window.status, window.start_at = "open", window.scheduled_start
                if card.stopped and not any(_running(s, t) for t in tasks):
                    close_window(s, window, now_, "stopped", now_)
                    closed += 1
                elif window.end_due is not None and window.end_due <= now_:
                    close_window(s, window, window.end_due, "end_due", now_)
                    closed += 1
                elif card.starts_at is None and tasks and all(t.status == "dropped" for t in tasks):
                    window.status, window.end_at, window.end_reason = "closed", now_, "held_expired"
                    window.verdict, window.memory = "unconfirmed", "ineligible"
                    closed += 1
    return closed


def _running(s: Session, task: Task) -> bool:
    if task.status != "live" or task.started_at is None:
        return False
    rows = s.execute(select(Execution.status).where(Execution.plan_id == task.episode_id,
                                                    Execution.task_id == task.task_id, Execution.kind == "run")
                     .order_by(Execution.at.desc(), Execution.received_at.desc()).limit(1)).scalars().all()
    return bool(rows) and rows[0] == "running"


def close_episodes(now: datetime | None = None) -> int:
    """`closed` when every task is done with, restores are in, every window is closed and its memory settled."""
    n = 0
    with session_scope() as s:
        rows = s.execute(select(Episode).where(Episode.status.in_(("notified", "held", "judged")),
                                               Episode.stage == "done")).scalars().all()
        ids = [(e.household_id, e.id) for e in rows]
    for hid, eid in ids:
        with session_scope() as s:
            lock_household(s, hid)
            ep = s.execute(select(Episode).where(Episode.id == eid).with_for_update()).scalar_one()
            tasks = s.execute(select(Task).where(Task.episode_id == eid)).scalars().all()
            if not tasks or any(t.status in ("live", "held") for t in tasks):
                continue
            pending_restore = False
            for t in tasks:
                if t.status == "cancelled" and t.restore:
                    got = s.execute(select(Execution.result_id).where(Execution.plan_id == eid,
                                                                      Execution.task_id == t.task_id,
                                                                      Execution.kind == "restore").limit(1)).first()
                    pending_restore = pending_restore or got is None
            if pending_restore:
                continue
            windows = s.execute(select(Window).where(Window.episode_id == eid)).scalars().all()
            if any(w.status != "closed" or w.memory not in ("written", "ineligible") for w in windows):
                continue
            ep.status, ep.closed_at = "closed", now or clock.now()
            n += 1
    return n


def run_jobs() -> None:
    """One pass of the §2.3 jobs that follow the clock (end_tasks, close_windows, close_episodes)."""
    for job in (end_tasks, close_windows, close_episodes):
        try:
            job()
        except Exception:                                   # a job error must not stop the next pass
            log.exception("%s failed", job.__name__)


# ----------------------------------------------------------------------------------------------- memory (§13.5)

def _change_text(task_trigger: dict | None, change: dict) -> str:
    prefix = {"guest_arrived": "손님 도착 뒤 ", "package.brought_in": "택배가 온 뒤 "}.get(
        (task_trigger or {}).get("event") or "", "")
    to = change.get("to")
    prop = change.get("property")
    if prop in ("color_temp", "color") and isinstance(to, dict) and "kelvin" in to:   # the Simulator reports color
        what = f"색온도 {to['kelvin']}K로"
    elif prop == "color":
        what = "색을 다른 색으로"
    elif isinstance(to, dict) and len(to) == 1:
        what = f"{prop} {next(iter(to.values()))}(으)로"
    else:
        what = f"{prop or '설정'}을 다르게"
    return f"{prefix}{what} 바꿈"


def memory_body(household_id: str, now: datetime | None = None) -> dict:
    from .s4_time import _parse_case_id, habit_time

    cfg, lists = get_config(), get_lists()
    now = now or clock.now()
    with session_scope() as s:
        rows = s.execute(select(Case).where(Case.source == "this_home", Case.household_id == household_id)
                         .order_by(Case.created_at.desc(), Case.case_id.desc())).scalars().all()
        groups: dict[tuple[str, tuple[str, ...]], dict] = {}
        for row in rows:
            tags = tuple(sorted((row.when or {}).get("calendar_tags") or []))
            g = groups.get((row.intent_id, tags))
            if g is None:
                try:
                    name = lists.intent_name(row.intent_id)
                except Exception:
                    name = row.intent_id
                g = groups[(row.intent_id, tags)] = {"intent_id": row.intent_id, "name": name,
                                                     "calendar_tags": list(tags), "episodes": [], "off_lines": [],
                                                     "changed": [], "habit_time": None}
            executed = (row.when or {}).get("executed_at")
            g["episodes"].append({"case_id": row.case_id, "verdict": row.verdict or "unconfirmed",
                                  "date": executed[:10] if executed else clock.iso(row.created_at)[:10]})
            did = {d["task_id"]: d for d in row.home_did or []}
            for fb in row.task_feedback or []:
                if fb.get("user") == "off" and fb.get("at"):
                    until = date.fromisoformat(fb["at"]) + timedelta(days=cfg.numbers.line_off_d)
                    g["off_lines"].append({"line": did.get(fb["task_id"], {}).get("line", fb["task_id"]),
                                           "until": until.isoformat(), "case_id": row.case_id})
                for ch in fb.get("changes") or []:
                    episode_id, _ = _parse_case_id(row.case_id, household_id)
                    task = s.execute(select(Task.trigger).where(Task.episode_id == episode_id,
                                                                Task.task_id == fb["task_id"])).scalars().first()
                    g["changed"].append({"device_type": ch.get("device_type", ""),
                                         "change": _change_text(task, ch), "case_id": row.case_id})
        for (intent_id, tags), g in groups.items():
            try:
                w = habit_time(s, household_id=household_id, intent_id=intent_id, tags=list(tags),
                               shared_at=now, now=now, cfg=cfg)
            except Exception:
                log.exception("habit time failed")
                w = None
            if w is not None and getattr(w, "source", None) == "habit":
                g["habit_time"] = {"weekday": clock.weekday_ko(w.start), "time": w.start.strftime("%H:%M")}
        return {"household_id": household_id, "intents": list(groups.values())}


def delete_memory(household_id: str, case_id: str) -> bool:
    with session_scope() as s:
        row = s.get(Case, case_id)
        if row is None or row.household_id != household_id or row.source != "this_home":
            return False
        s.delete(row)
        return True
