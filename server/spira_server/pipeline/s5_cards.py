"""S5 cards (spec §11.2, §11.4, §11.5): card text, line states (C-7) and the card body (contracts/schemas/card.json).

`line_state` and `end_state` are pure functions over what the server saw; the S6 hub API feeds them acks, results
and user events. `card_body` builds the JSON the app polls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import Config, get_config
from ..db.models import Card, CardLine, Task
from ..kb.lists import KbLists, get_lists

FINAL = ("completed", "failed", "blocked", "unknown", "unverifiable")


# --------------------------------------------------------------------------------------------- text (§11.4)

def event_word(bundle: dict, lists: KbLists) -> str:
    tags = bundle.get("calendar_tags") or []
    if tags:
        return tags[0]
    event = (bundle.get("situation") or {}).get("event")
    if event:
        return event
    if bundle["intent_id"] == "unclassified":
        return "이번"
    return lists.intent_name(bundle["intent_id"]).split("·")[0].strip()


def card_text(bundle: dict, starts_at: datetime | None, cfg: Config | None = None,
              lists: KbLists | None = None) -> tuple[str, str]:
    """(template id, text)."""
    cfg, lists = cfg or get_config(), lists or get_lists()
    t = cfg.card_templates["common.v1"]
    event = event_word(bundle, lists)
    if starts_at is None:
        return "common.v1", t["held"].replace("{event}", event)
    theme = (bundle.get("situation") or {}).get("theme")
    template = t["with_time_theme"] if theme else t["with_time"]
    text = template.replace("{요일}", clock.weekday_ko(starts_at)).replace("{event}", event)
    return "common.v1", text.replace("{theme}", theme or "")


# ------------------------------------------------------------------------------------------- line state (§11.5)

@dataclass
class ActionResult:
    device: str
    cmd: str
    status: str
    at: datetime
    received_at: datetime
    operation_id: str | None = None
    reason: str | None = None


@dataclass
class LineInput:
    checked: bool = True
    card_stopped: bool = False
    task_status: str = "live"                 # held / live / cancelled / dropped / ended
    rejected: bool = False                    # ack rejected the task or no ack in time
    actions: list[tuple[str, str]] = field(default_factory=list)       # expected (device, cmd)
    results: list[ActionResult] = field(default_factory=list)
    user_changed: bool = False                # a by:user change on a device after the first completed result


def _latest(results: list[ActionResult], device: str, cmd: str) -> ActionResult | None:
    mine = [r for r in results if r.device == device and r.cmd == cmd]
    if not mine:
        return None
    ops = sorted({r.operation_id for r in mine}, key=lambda o: max(r.at for r in mine if r.operation_id == o))
    latest_op = [r for r in mine if r.operation_id == ops[-1]]
    finals = [r for r in latest_op if r.status in FINAL]
    pool = finals or latest_op                 # a final result is never replaced by a later running
    return max(pool, key=lambda r: (r.at, r.received_at))


def line_state(x: LineInput) -> tuple[str, str | None]:
    """(state, blocked reason or None). Priority: off, stopped > user_changed > done, partial > running >
    failed, unknown, blocked > scheduled."""
    if not x.checked:
        return "off", None
    if x.card_stopped:
        return "stopped", None
    if x.task_status in ("cancelled", "dropped", "held"):
        return x.task_status, None
    if x.rejected:
        return "failed", "rejected"
    latest = [_latest(x.results, d, c) for d, c in x.actions]
    statuses = [r.status if r else None for r in latest]
    completed = [s == "completed" for s in statuses]
    final = [s in FINAL for s in statuses]
    if statuses and all(completed):
        state = "done"
    elif any(completed) and all(final):
        state = "partial"
    elif any(completed):
        state = "running"
    elif statuses and all(final):
        if "failed" in statuses:
            state = "failed"
        elif "blocked" in statuses:
            reason = next(r.reason for r in latest if r and r.status == "blocked")
            return "blocked", reason
        else:
            state = "unknown"
    elif "running" in statuses:
        state = "running"
    else:
        state = "scheduled"
    if x.user_changed and state in ("done", "partial"):
        return "user_changed", None
    return state, None


def end_state(items: list[str], restore: bool, ended: bool) -> str | None:
    """From the restore result item statuses (spec §11.5 step 5)."""
    if items:
        if any(s in ("failed", "unknown") for s in items):
            return "restore_failed"
        if "withheld_end_not_observed" in items:
            return "withheld"
        if "skipped_user_changed" in items:
            return "kept_user_change"
        return "restored"
    if ended and not restore:
        return "none"
    return None


# ------------------------------------------------------------------------------------------ card body (§11.2)

def line_when(task: Task) -> dict | None:
    if task.status == "held" or task.trigger is None:
        return None
    if "time" in task.trigger:
        return {"time": task.trigger["time"]}
    return {"event": task.trigger["event"]}


def waiting_for(lines: list[tuple[CardLine, Task]], now: datetime) -> str | None:
    """The event trigger of a scheduled line whose window has opened (R23); guest_arrived before event_end."""
    events = []
    for line, task in lines:
        trig = task.trigger or {}
        window = trig.get("window")
        if line.state == "scheduled" and trig.get("event") in ("guest_arrived", "event_end") and window:
            if clock.parse(window["from"]) <= now:
                events.append(trig["event"])
    for e in ("guest_arrived", "event_end"):
        if e in events:
            return e
    return None


def card_body(s: Session, card: Card, now: datetime | None = None) -> dict:
    now = now or clock.now()
    rows = s.execute(
        select(CardLine, Task).join(Task, (Task.task_id == CardLine.task_id) & (Task.episode_id == card.episode_id))
        .where(CardLine.card_id == card.id).order_by(CardLine.position)
    ).all()
    lines = [{"task_id": ln.task_id, "text": t.line or "", "checked": ln.checked, "when": line_when(t),
              "state": ln.state, "end_state": ln.end_state, "note": ln.note} for ln, t in rows]
    done = sum(1 for ln, _ in rows if ln.state in ("done", "partial", "user_changed"))
    total = sum(1 for ln, _ in rows if ln.state not in ("off", "stopped", "cancelled"))
    return {
        "card_id": card.id, "episode_id": card.episode_id, "intent_id": card.intent_id, "template": card.template,
        "text": card.text, "starts_at": clock.iso(card.starts_at), "lines": lines,
        "summary": {"done": done, "total": total, "waiting_for": waiting_for(rows, now)},
        "stopped": card.stopped, "buttons": [] if card.stopped else ["stop"], "notify": card.notify,
        "updated_at": clock.iso(card.updated_at),
    }
