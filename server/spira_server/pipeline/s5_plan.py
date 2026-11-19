"""S5 Plan confirmation (spec §11.1, §11.3): safety net, merge with the home's live tasks, fridge notices, cards,
store, publish a plan version, episode status. No LLM.

    finalize(episode_id, s4_result)   one transaction under the household lock
    publish(s, episode, now)          new plan version from the stored tasks
    pulled_plans(s, household_id)     latest versions the hub still pulls (spec §11.3; used by GET /v1/hub/plans)
    apply_ack(plan_id, ack)           hub ack of a plan version (spec §12.2; POST /v1/hub/plans/{plan_id}/ack)
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..config import Config, get_config
from ..db.engine import lock_household, next_id, session_scope
from ..db.models import (
    Card,
    CardLine,
    CareNoticeShown,
    DeviceList,
    Episode,
    Execution,
    Household,
    Plan,
    Task,
    Window,
)
from ..kb.lists import get_lists
from .s4_tasks import Catalog, Draft, S4Result, catalog_from
from .s5_cards import card_text, touch

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------- safety net (§11.1 ①)

def command_allowed(way: str, cmd: str, policy: dict) -> bool:
    if any(w in cmd for w in policy.get("deny_words", [])):
        return False
    if way == "run":
        return cmd in policy.get("run", [])
    if way == "standby":
        return re.match(policy.get("standby_pattern", "^$"), cmd) is not None
    if way == "notice":
        return cmd in policy.get("notice", [])
    return False


def value_ok(value, schema) -> bool:
    if schema is None:
        return value is None
    if schema == "text":
        return isinstance(value, str) and bool(value)
    if not isinstance(value, dict) or set(value) != set(schema):
        return False
    for p, rule in schema.items():
        v = value[p]
        if "enum" in rule:
            if v not in rule["enum"]:
                return False
        elif isinstance(v, bool) or not isinstance(v, (int, float)) or not rule["range"][0] <= v <= rule["range"][1]:
            return False
    return True


def _t(value: str | None) -> datetime | None:
    return clock.parse(value) if value else None


def safety_reason(d: Draft, catalog: Catalog, body: dict, now: datetime, cfg: Config) -> str | None:
    """Reason to drop the task, or None. Actions on a device outside `target_room` are removed from the task
    (kept in meta.room_removed); only a task left with no action is dropped as room_mismatch."""
    n, policy = cfg.numbers, cfg.command_policy
    raw = {x["id"]: x for x in body.get("devices", [])}
    for a in d.actions:
        if not command_allowed(d.way, a["cmd"], policy):
            return "unsafe_cmd"
    for a in d.actions:
        dev = catalog.get(a["device"])
        if dev is None or a["cmd"] not in dev.commands or a["cmd"] in (raw.get(a["device"], {}).get("never") or []):
            return "not_delegated"
    for a in d.actions:
        if not value_ok(a.get("value"), catalog.get(a["device"]).commands[a["cmd"]]):
            return "value_out_of_range"
    if d.target_room is not None:
        other = [a for a in d.actions if catalog.get(a["device"]).room != d.target_room]
        if len(other) == len(d.actions):
            return "room_mismatch"
        if other:                                    # drop only the actions in another room; recorded, not shown
            d.meta["room_removed"] = [{"device": a["device"], "cmd": a["cmd"],
                                       "room": catalog.get(a["device"]).room} for a in other]
            d.actions = [a for a in d.actions if a not in other]
    if d.trigger is None:
        return None                                              # held: times come later
    t = _t(d.trigger.get("time"))
    if t is not None:
        quiet_from, quiet_to = n.quiet_hours
        if any(catalog.get(a["device"]).noisy for a in d.actions) and (t.hour >= quiet_from or t.hour < quiet_to):
            return "quiet_hours"
        if t < now - timedelta(minutes=n.late_grace_min):
            return "late"
        end_t = _t(d.end.get("time")) or _t(d.end.get("or_time"))
        if end_t is not None and end_t <= t:
            return "late"
    window = d.trigger.get("window")
    if window and clock.parse(window["to"]) < now:
        return "late"
    return None


# ------------------------------------------------------------------------------------------- merge (§11.1 ②)

@dataclass
class Slot:
    """A task competing for a device: a new draft or a live stored task."""
    task_id: str
    episode_id: str
    devices: set[str]
    keys: set[tuple[str, str, str]]           # (device, cmd, value repr)
    start: datetime
    end: datetime
    rank: int                                 # 0 started, 1 per-item, 2 confirmed plan, 3 new plan
    draft: Draft | None = None
    row: Task | None = None


def interval(trigger: dict | None, end: dict, now: datetime, cfg: Config) -> tuple[datetime, datetime] | None:
    n = cfg.numbers
    if trigger is None:
        return None
    if "time" in trigger:
        start = clock.parse(trigger["time"])
        stop = _t(end.get("time")) or _t(end.get("or_time"))
    elif trigger.get("window"):
        start = clock.parse(trigger["window"]["from"])
        stop = _t(end.get("or_time")) or clock.parse(trigger["window"]["to"])
    elif trigger.get("event") == "package.brought_in" and not trigger.get("released"):
        start, stop = now, now + timedelta(minutes=n.standby_max_min)
    else:
        start = _t(trigger.get("at")) or now
        stop = None
    if stop is None:
        if end.get("or_after"):
            stop = start + clock.parse_duration(end["or_after"])
        else:
            stop = start + timedelta(minutes=n.end_fallback_min)
    return start, stop


def _key(a: dict) -> tuple[str, str, str]:
    return (a["device"], a["cmd"], repr(sorted(a["value"].items())) if isinstance(a.get("value"), dict)
            else repr(a.get("value")))


def _is_notice(slot: Slot) -> bool:
    return all(k[1] == "show_notice" for k in slot.keys)


def _slot(task_id, episode_id, actions, trigger, end, rank, now, cfg, draft=None, row=None) -> Slot | None:
    iv = interval(trigger, end, now, cfg)
    if iv is None:
        return None
    return Slot(task_id, episode_id, {a["device"] for a in actions}, {_key(a) for a in actions}, iv[0], iv[1], rank,
                draft, row)


def _n(task_id: str) -> int:
    return int(task_id.rsplit("#", 1)[1])


def _beats(a: Slot, b: Slot) -> bool:
    return (a.rank, a.start, _n(a.task_id)) < (b.rank, b.start, _n(b.task_id))


# ------------------------------------------------------------------------------------------ finalize (§11.1)

@dataclass
class Outcome:
    published: int | None = None
    card_ids: list[str] = field(default_factory=list)
    dropped: dict[str, str] = field(default_factory=dict)        # task_id -> reason
    cancelled_elsewhere: list[tuple[str, str]] = field(default_factory=list)   # (episode, task_id)
    status: str = ""


def finalize(episode_id: str, s4: S4Result, *, now: datetime | None = None) -> Outcome:
    cfg = get_config()
    out = Outcome()
    with session_scope() as s:
        ep0 = s.get(Episode, episode_id)
        household = lock_household(s, ep0.household_id)
        now = now or clock.now()                   # read under the lock: card updated_at vs the poll (§12.2)
        ep = s.execute(select(Episode).where(Episode.id == episode_id).with_for_update()).scalar_one()
        dl = s.get(DeviceList, ep.household_id)
        body = dl.body if dl else {"devices": []}
        catalog = catalog_from(body) or Catalog([], 0)
        bundles = (ep.intent or {}).get("bundles") or []
        drafts = list(s4.drafts)
        ep.next_task_n = max(ep.next_task_n, s4.next_task_n)

        if household.paused:                                 # nothing new goes live while paused
            for d in drafts:
                out.dropped[d.task_id] = "paused"
            _store(s, ep, drafts, {}, out, now)
            ep.status, ep.judged, ep.stage = "judged", True, "done"
            out.status = ep.status
            return out

        # ① safety net
        kept: list[Draft] = []
        for d in drafts:
            reason = safety_reason(d, catalog, body, now, cfg)
            if reason:
                out.dropped[d.task_id] = reason
            else:
                kept.append(d)

        # ③ fridge notices (before the merge, which never lets notices conflict)
        kept = _notices(s, household.id, kept, out, cfg)

        # ② merge with the home's live tasks and between new drafts
        kept = _merge(s, ep, kept, out, now, cfg)

        # ④ cards ⑤ store
        cards = _cards(s, ep, bundles, kept, s4, now, cfg, out)
        _store(s, ep, drafts, cards, out, now)

        # ⑥ publish
        if any(d.task_id not in out.dropped and not d.held for d in drafts):
            out.published = publish(s, ep, now, dl.revision if dl else 0)

        # ⑦ status
        live_lines = any(not d.held for d in kept if d.source == "situation")
        if out.card_ids and live_lines:
            ep.status = "notified"
        elif out.card_ids:
            ep.status = "held"
        else:
            ep.status = "judged"
        ep.judged, ep.stage = True, "done"
        intent = dict(ep.intent or {})
        intent["s4"] = {"dropped": s4.dropped, "skipped_bundles": {str(k): v for k, v in s4.skipped_bundles.items()}}
        ep.intent = intent
        out.status = ep.status
    return out


def _notices(s: Session, household_id: str, drafts: list[Draft], out: Outcome, cfg: Config) -> list[Draft]:
    n = cfg.numbers
    notices = [d for d in drafts if d.source == "item" and d.actions[0]["cmd"] == "show_notice"]
    if not notices:
        return drafts
    shown = {(r.item_type, r.kind): r.count for r in s.execute(
        select(CareNoticeShown).where(CareNoticeShown.household_id == household_id)).scalars()}
    keep = []
    for d in notices:
        item, kind = d.meta.get("item"), d.meta.get("kind")
        if not d.meta.get("intent_change") and shown.get((item, kind or ""), 0) >= n.notice_repeat_max:
            out.dropped[d.task_id] = "repeated_notice"
            continue
        keep.append(d)
    order = {"prep": 1, "storage": 2}
    keep.sort(key=lambda d: (0 if d.meta.get("intent_change") else 1, order.get(d.meta.get("kind"), 3), _n(d.task_id)))
    for d in keep[n.notices_per_screen:]:
        out.dropped[d.task_id] = "notices_per_screen"
    allowed = {d.task_id for d in keep[: n.notices_per_screen]}
    return [d for d in drafts if d not in notices or d.task_id in allowed]


def _merge(s: Session, ep: Episode, drafts: list[Draft], out: Outcome, now: datetime, cfg: Config) -> list[Draft]:
    live_rows = s.execute(
        select(Task).join(Episode, Episode.id == Task.episode_id)
        .where(Episode.household_id == ep.household_id, Task.status == "live").order_by(Task.episode_id, Task.task_id)
    ).scalars().all()
    slots: list[Slot] = []
    for row in live_rows:
        started = row.started_at is not None or (row.meta or {}).get("start_uncertain")
        rank = 0 if started else (1 if row.source == "item" else 2)
        sl = _slot(row.task_id, row.episode_id, row.actions, row.trigger, row.end, rank, now, cfg, row=row)
        if sl:
            slots.append(sl)
    new: list[Slot] = []
    for d in drafts:
        sl = _slot(d.task_id, ep.id, d.actions, d.trigger, d.end, 1 if d.source == "item" else 3, now, cfg, draft=d)
        if sl:
            new.append(sl)
    losers: set[int] = set()
    for sl in new:
        for other in slots + [x for x in new if x is not sl]:
            if id(other) in losers or id(sl) in losers:
                continue
            if not (sl.devices & other.devices) or _is_notice(sl) or _is_notice(other):
                continue
            if not (sl.start < other.end and other.start < sl.end):
                continue
            if sl.keys <= other.keys and other.draft is None:   # same device + cmd + value: keep the existing one
                losers.add(id(sl))
                continue
            loser = other if _beats(sl, other) else sl
            losers.add(id(loser))
    keep = []
    for sl in new:
        if id(sl) in losers:
            out.dropped[sl.task_id] = "overlap"
    for d in drafts:
        if d.task_id not in out.dropped:
            keep.append(d)
    touched: dict[str, Episode] = {}
    for sl in slots:
        if id(sl) in losers and sl.row is not None:
            row = sl.row
            row.status = "cancelled"
            row.drop_reason = "overlap"
            started = row.started_at is not None or (row.meta or {}).get("start_uncertain")
            row.restore = bool(started and row.end.get("restore"))
            _line_state(s, row, "cancelled")
            out.cancelled_elsewhere.append((row.episode_id, row.task_id))
            if row.episode_id != ep.id:
                touched[row.episode_id] = s.execute(
                    select(Episode).where(Episode.id == row.episode_id).with_for_update()).scalar_one()
    dl = s.get(DeviceList, ep.household_id)
    for other in sorted(touched.values(), key=lambda e: e.id):
        publish(s, other, now, dl.revision if dl else 0)
    return keep


def _line_state(s: Session, task: Task, state: str) -> None:
    for line in s.execute(select(CardLine).where(CardLine.task_id == task.task_id).join(
            Card, Card.id == CardLine.card_id).where(Card.episode_id == task.episode_id)).scalars():
        line.state = state


def _cards(s: Session, ep: Episode, bundles: list[dict], kept: list[Draft], s4: S4Result, now: datetime,
           cfg: Config, out: Outcome) -> dict[str, str]:
    """One card per bundle with situation tasks (held or live). Returns task_id -> card_id."""
    lists = get_lists()
    task_card: dict[str, str] = {}
    by_bundle: dict[int, list[Draft]] = {}
    for d in kept:
        if d.source == "situation" and d.bundle is not None:
            by_bundle.setdefault(d.bundle, []).append(d)
    for idx in sorted(by_bundle):
        lines = by_bundle[idx][: cfg.numbers.max_lines]
        when = s4.whens.get(idx)
        bundle = bundles[idx]
        template, text = card_text(bundle, when.start if when else None, cfg, lists)
        card = Card(id=next_id(s, "nc", "card_id_seq"), episode_id=ep.id, bundle_index=idx,
                    ordinal=ep.next_card_ordinal, intent_id=bundle["intent_id"], template=template, text=text,
                    starts_at=when.start if when else None, stopped=False, archived=False, notify=True,
                    updated_at=now)
        ep.next_card_ordinal += 1
        s.add(card)
        s.flush()
        s.add(Window(id=next_id(s, "ow", "window_id_seq"), episode_id=ep.id, card_id=card.id,
                     scheduled_start=when.start if when else None,
                     end_due=(when.end + timedelta(minutes=cfg.numbers.end_fallback_min)) if when else None,
                     status="pending", memory="pending", checks={}))
        for pos, d in enumerate(lines, start=1):
            task_card[d.task_id] = card.id
        out.card_ids.append(card.id)
    return task_card


def _store(s: Session, ep: Episode, drafts: list[Draft], cards: dict[str, str], out: Outcome, now: datetime) -> None:
    positions: dict[str, int] = {}
    for d in drafts:
        reason = out.dropped.get(d.task_id)
        if reason is None and d.source == "situation" and d.task_id not in cards:
            reason = "card_limit"
            out.dropped[d.task_id] = reason
        status = "dropped" if reason else ("held" if d.held else "live")
        meta = dict(d.meta)
        if d.bundle is not None:
            meta["bundle"] = d.bundle
        s.add(Task(episode_id=ep.id, task_id=d.task_id, card_id=cards.get(d.task_id), source=d.source, way=d.way,
                   status=status, need=d.need, line=d.line, actions=d.actions, trigger=d.trigger, end=d.end,
                   target_room=d.target_room, end_after_start_minutes=d.end_after_start_minutes, meta=meta,
                   drop_reason=reason))
        if d.task_id in cards and not reason:
            card_id = cards[d.task_id]
            positions[card_id] = positions.get(card_id, 0) + 1
            s.add(CardLine(card_id=card_id, task_id=d.task_id, position=positions[card_id], checked=True,
                           state="held" if d.held else "scheduled"))
    s.flush()


# ------------------------------------------------------------------------------------------- publish (§11.3)

def protective(task: Task, catalog: Catalog, patterns: list[str]) -> bool:
    for a in task.actions:
        dev = catalog.get(a["device"])
        name = f"{dev.type if dev else '?'}.{a['cmd']}"
        if any(fnmatch.fnmatchcase(name, p) for p in patterns):
            return True
    return False


def contract_task(task: Task, catalog: Catalog, patterns: list[str]) -> dict:
    body = {"task_id": task.task_id, "source": task.source, "way": task.way}
    if protective(task, catalog, patterns):
        body["protective"] = True
    body.update(actions=task.actions, trigger=task.trigger, end=task.end)
    return body


def publish(s: Session, ep: Episode, now: datetime, devices_revision: int) -> int:
    cfg = get_config()
    dl = s.get(DeviceList, ep.household_id)
    catalog = catalog_from(dl.body if dl else None) or Catalog([], 0)
    patterns = cfg.command_policy.get("protective", [])
    tasks = s.execute(select(Task).where(Task.episode_id == ep.id)).scalars().all()
    live = sorted((t for t in tasks if t.status == "live"), key=lambda t: _n(t.task_id))
    cancelled = sorted((t for t in tasks if t.status == "cancelled"), key=lambda t: _n(t.task_id))
    version = ep.plan_version + 1
    body = {
        "plan_id": ep.id, "household_id": ep.household_id, "plan_version": version,
        "devices_revision": devices_revision, "sent_at": clock.iso(now),
        "tasks": [contract_task(t, catalog, patterns) for t in live],
        "cancelled": [{"task_id": t.task_id, "restore": bool(t.restore)} for t in cancelled],
    }
    s.add(Plan(episode_id=ep.id, version=version, body=body, devices_revision=devices_revision, created_at=now))
    ep.plan_version = version
    return version


def pulled_plans(s: Session, household_id: str) -> list[dict]:
    """Latest version of every episode still pulled (spec §11.3): a task is live; a cancelled task with restore true
    has no restore result yet; or the latest version is not acked yet."""
    latest = s.execute(
        select(Plan).join(Episode, Episode.id == Plan.episode_id)
        .where(Episode.household_id == household_id, Plan.version == Episode.plan_version)
        .order_by(Plan.episode_id)
    ).scalars().all()
    out = []
    for plan in latest:
        live = s.execute(select(func.count()).select_from(Task).where(
            Task.episode_id == plan.episode_id, Task.status == "live")).scalar_one()
        pending_restore = False
        for t in s.execute(select(Task).where(Task.episode_id == plan.episode_id, Task.status == "cancelled",
                                              Task.restore.is_(True))).scalars():
            done = s.execute(select(func.count()).select_from(Execution).where(
                Execution.plan_id == plan.episode_id, Execution.task_id == t.task_id,
                Execution.kind == "restore")).scalar_one()
            pending_restore = pending_restore or done == 0
        if live or pending_restore or plan.ack is None:
            out.append(plan.body)
    return out


# ----------------------------------------------------------------------------------------------- ack (§12.2)

class AckError(ValueError):
    """A task id in rejected_tasks that is not a task of that version (422)."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path = path


def apply_ack(plan_id: str, ack: dict, *, now: datetime | None = None) -> str:
    """Store a hub ack; one transaction under the household lock. Returns what happened:
    `applied` (latest version), `stale` (older version: stored on it only), `repeat` (same body again) or
    `ignored` (that version was already acked with another body; the first ack stands).
    Raises LookupError for an unknown plan version and AckError for an unknown rejected task id."""
    cfg = get_config()
    with session_scope() as s:
        ep0 = s.get(Episode, plan_id)
        if ep0 is None:
            raise LookupError(plan_id)
        lock_household(s, ep0.household_id)
        ep = s.execute(select(Episode).where(Episode.id == plan_id).with_for_update()).scalar_one()
        now = now or clock.now()
        plan = s.get(Plan, (plan_id, ack["plan_version"]))
        if plan is None:
            raise LookupError(f"{plan_id} v{ack['plan_version']}")
        ids = [t["task_id"] for t in plan.body["tasks"]]
        for i, r in enumerate(ack["rejected_tasks"]):
            if r["task_id"] not in ids:
                raise AckError(f"rejected_tasks[{i}].task_id", f"{r['task_id']} is not a task of version "
                                                               f"{plan.version}.")
        if plan.ack is not None:
            return "repeat" if plan.ack == ack else "ignored"
        plan.ack, plan.acked_at = ack, now
        if plan.version < ep.plan_version:
            return "stale"                       # never changes tasks of a newer version
        if ack["status"] == "rejected":          # whole plan unreadable: every task new in this version fails
            prev = s.get(Plan, (plan_id, plan.version - 1))
            before = {t["task_id"] for t in prev.body["tasks"]} if prev else set()
            failed = [t for t in ids if t not in before]
        else:
            failed = [r["task_id"] for r in ack["rejected_tasks"]]
        note = cfg.card_templates["lines"]["rejected_note"]
        touched: dict[str, Card] = {}
        for tid in dict.fromkeys(failed):
            task = s.get(Task, (plan_id, tid))
            if task is None or task.status != "live":
                continue
            task.status, task.drop_reason = "dropped", "rejected"     # never re-planned (§14 keeps it dropped)
            for line, card in s.execute(select(CardLine, Card).join(Card, Card.id == CardLine.card_id).where(
                    Card.episode_id == plan_id, CardLine.task_id == tid)).all():
                line.state, line.note = "failed", note
                touched[card.id] = card
        for card in touched.values():
            touch(s, card, now)
        return "applied"


def household_paused(s: Session, household_id: str) -> bool:
    h = s.get(Household, household_id)
    return bool(h and h.paused)
