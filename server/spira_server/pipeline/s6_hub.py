"""S6 hub inputs (spec §12.2, §12.4): events and execution results, and the card line recompute they drive
(§11.5). One transaction per input under the household lock (§2.4); a duplicate `event_id` / `result_id` changes
nothing.

    apply_events(household_id, body)       POST /v1/hub/events      -> {accepted, rejected, plans_changed}
    apply_execution(household_id, body)    POST /v1/hub/executions  -> {duplicate}
    refresh_task_lines(s, task, now)       recompute the card line(s) of one task (also used by S7 and end_tasks)
"""

from __future__ import annotations

import logging
from datetime import datetime

from spira_contracts.validate import errors
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_config
from ..db.engine import lock_household, session_scope
from ..db.models import Card, CardLine, CareNoticeShown, DeviceList, Episode, Event, Execution, Plan, Task, Window
from . import s5_plan
from .s5_cards import ActionResult, LineInput, end_state, line_state, touch

log = logging.getLogger(__name__)

HOME_EVENTS = ("package.brought_in", "guest_arrived", "event_end")


class HubInputError(Exception):
    """422 / 404 / 403 for an execution result (the route maps `code` to the status)."""

    def __init__(self, code: str, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.path = code, message, path


# ---------------------------------------------------------------------------------------------- line state

def _devices(s: Session, household_id: str) -> dict[str, dict]:
    dl = s.get(DeviceList, household_id)
    return {d["id"]: d for d in (dl.body.get("devices", []) if dl else [])}


def _josa(word: str) -> str:
    last = word[-1] if word else ""
    final = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return "을" if final else "를"


def _first_completed(results: list[Execution]) -> datetime | None:
    done = [r.at for r in results if r.status == "completed"]
    return min(done) if done else None


def refresh_task_lines(s: Session, task: Task, now: datetime) -> bool:
    """Recompute the line(s) of `task` from what the server saw (§11.5). Touches the card when anything changed.
    Returns True when a line changed."""
    cfg = get_config()
    lines = s.execute(select(CardLine, Card).join(Card, Card.id == CardLine.card_id)
                      .where(Card.episode_id == task.episode_id, CardLine.task_id == task.task_id)).all()
    if not lines:
        return False
    ep = s.get(Episode, task.episode_id)
    devices = _devices(s, ep.household_id)
    runs = s.execute(select(Execution).where(Execution.plan_id == task.episode_id, Execution.task_id == task.task_id,
                                             Execution.kind == "run")).scalars().all()
    restores = s.execute(select(Execution).where(Execution.plan_id == task.episode_id,
                                                 Execution.task_id == task.task_id, Execution.kind == "restore")
                         .order_by(Execution.at, Execution.received_at)).scalars().all()
    first_done = _first_completed(runs)
    task_devices = {a["device"] for a in task.actions}
    changed_device = None
    if first_done is not None:
        window = s.execute(select(Window).join(Card, Card.id == Window.card_id)
                           .where(Card.id == lines[0][1].id)).scalar_one_or_none()
        until = window.end_at if window is not None and window.status == "closed" else None
        q = select(Event).where(Event.household_id == ep.household_id, Event.source.in_(task_devices),
                                Event.type.like("%.changed"), Event.at > first_done).order_by(Event.at)
        for ev in s.execute(q).scalars():
            if (ev.payload or {}).get("by") == "user" and (until is None or ev.at <= until):
                changed_device = ev.source
                break
    per_device: dict[str, str] = {}                    # latest status per device over every restore result
    for r in restores:
        for i in r.body.get("items", []):
            per_device[i["device"]] = i["status"]
    items = list(per_device.values())
    if changed_device is None and "skipped_user_changed" in items and first_done is not None:
        changed_device = next(d for d, st in per_device.items() if st == "skipped_user_changed")

    meta = task.meta or {}
    templates = cfg.card_templates["lines"]
    any_change = False
    for line, card in lines:
        x = LineInput(
            checked=line.checked, card_stopped=card.stopped, task_status=task.status if task.status != "ended" else
            "live", rejected=task.status == "dropped" and task.drop_reason == "rejected",
            actions=[(a["device"], a["cmd"]) for a in task.actions],
            results=[ActionResult(r.device, r.cmd, r.status, r.at, r.received_at, r.operation_id, r.reason)
                     for r in runs if r.device and r.cmd and r.status],
            user_changed=changed_device is not None,
        )
        state, reason = line_state(x)
        note = None
        if state == "failed" and x.rejected:
            note = templates["rejected_note"]
        elif state == "blocked":
            notes = templates["blocked_note"]
            note = notes.get(reason or "", notes["default"])
        elif state == "dropped":
            note = templates["dropped_note"]
        if task.status == "ended" and meta.get("never_fired") and state == "scheduled":
            state, note = "dropped", templates["dropped_note"]
        restore_flag = bool(task.restore) if task.status == "cancelled" else bool((task.end or {}).get("restore"))
        e_state = None
        if state not in ("off", "held", "dropped") and not (state == "failed" and x.rejected):
            e_state = end_state(items, restore_flag, task.status == "ended")
            if meta.get("restore_timeout") and not items:
                e_state = "restore_failed"
        if e_state == "withheld":
            note = templates["withheld_note"]
        if state == "user_changed" or e_state == "kept_user_change":
            dev = devices.get(changed_device or "", {})
            name = cfg.device_names.get(dev.get("type", ""), dev.get("type", "기기"))
            note = templates["user_changed_note"].replace("{device_name}", name).replace("{을/를}", _josa(name))
        if (line.state, line.end_state, line.note) != (state, e_state, note):
            line.state, line.end_state, line.note = state, e_state, note
            touch(s, card, now)
            any_change = True
    return any_change


def _tasks_on_device(s: Session, household_id: str, device: str) -> list[Task]:
    rows = s.execute(select(Task).join(Episode, Episode.id == Task.episode_id)
                     .where(Episode.household_id == household_id, Episode.status != "closed",
                            Task.status.in_(("live", "ended", "cancelled")))).scalars().all()
    return [t for t in rows if any(a["device"] == device for a in t.actions)]


# ----------------------------------------------------------------------------------------------- events

def _release_packages(s: Session, household_id: str, event: dict, now: datetime) -> bool:
    """§12.4: release every waiting package task of the most recent episode that has one; publish."""
    rows = s.execute(select(Task, Episode).join(Episode, Episode.id == Task.episode_id)
                     .where(Episode.household_id == household_id, Task.status == "live")
                     .order_by(Episode.shared_at.desc(), Episode.id.desc())).all()
    waiting = [(t, e) for t, e in rows
               if (t.trigger or {}).get("event") == "package.brought_in" and not (t.trigger or {}).get("released")]
    if not waiting:
        return False
    episode = waiting[0][1]
    ep = s.execute(select(Episode).where(Episode.id == episode.id).with_for_update()).scalar_one()
    for task, e in waiting:
        if e.id != ep.id:
            continue
        task.trigger = {"event": "package.brought_in", "released": True, "at": event["at"]}
        if task.actions and task.actions[0]["cmd"] == "show_notice":
            item, kind = (task.meta or {}).get("item"), (task.meta or {}).get("kind") or ""
            if item:
                row = s.get(CareNoticeShown, (household_id, item, kind))
                if row is None:
                    s.add(CareNoticeShown(household_id=household_id, item_type=item, kind=kind, count=1))
                else:
                    row.count += 1
    dl = s.get(DeviceList, household_id)
    s5_plan.publish(s, ep, now, dl.revision if dl else 0)
    return True


def _note_end_event(s: Session, household_id: str, event: dict) -> None:
    """Tasks whose end rule waits for this event (with `by` if set) get `meta.end_seen_at` (+ `after`);
    `end_tasks` ends them (§11.8)."""
    at = clock.parse(event["at"])
    by = (event.get("payload") or {}).get("by")
    rows = s.execute(select(Task).join(Episode, Episode.id == Task.episode_id)
                     .where(Episode.household_id == household_id, Task.status == "live")).scalars().all()
    for task in rows:
        end = task.end or {}
        if end.get("on") != event["type"] or (end.get("by") and end["by"] != by):
            continue
        if event["source"] != "hub" and all(a["device"] != event["source"] for a in task.actions):
            continue
        if event["type"] != "event_end" and not started(task) and not _fired(task, at):
            continue                                 # e.g. a door opened before the notice was ever shown
        meta = dict(task.meta or {})
        if "end_seen_at" in meta:
            continue
        due = at + clock.parse_duration(end["after"]) if end.get("after") else at
        meta["end_seen_at"] = clock.iso(due)
        task.meta = meta


def _fired(task: Task, at: datetime) -> bool:
    trig = task.trigger or {}
    if trig.get("released"):
        return clock.parse(trig["at"]) <= at if trig.get("at") else True
    return "time" in trig and clock.parse(trig["time"]) <= at


def apply_events(household_id: str, raw) -> dict:
    """POST /v1/hub/events. The body is the contract's event batch (an array, `event_batch.json`); each element is
    checked on its own and stored in its own transaction."""
    from . import s7_observe

    if not isinstance(raw, list) or not raw:
        raise HubInputError("validation_error", "Body must be a non-empty array of events.", "(root)")
    accepted: list[str] = []
    rejected: list[dict] = []
    plans_changed = False
    for i, ev in enumerate(raw):
        eid = ev.get("event_id") if isinstance(ev, dict) and isinstance(ev.get("event_id"), str) else str(i)
        found = errors(ev, "event.json")
        if found:
            rejected.append({"event_id": eid, "code": "validation_error", "message": found[0]})
            continue
        if ev["household_id"] != household_id:
            rejected.append({"event_id": eid, "code": "forbidden", "message": "Another household's event."})
            continue
        with session_scope() as s:
            lock_household(s, household_id)
            now = clock.now()
            if ev["source"] != "hub" and ev["source"] not in _devices(s, household_id):
                rejected.append({"event_id": eid, "code": "validation_error", "message": "Unknown device."})
                continue
            if s.get(Event, eid) is not None:
                accepted.append(eid)
                continue
            s.add(Event(event_id=eid, household_id=household_id, type=ev["type"], source=ev["source"],
                        at=clock.parse(ev["at"]), payload=ev.get("payload") or {}, received_at=now))
            s.flush()
            if ev["type"] == "package.brought_in":
                plans_changed = _release_packages(s, household_id, ev, now) or plans_changed
            _note_end_event(s, household_id, ev)
            if ev["type"].endswith(".changed") and (ev.get("payload") or {}).get("by") == "user":
                for task in _tasks_on_device(s, household_id, ev["source"]):
                    refresh_task_lines(s, task, now)
            if ev["type"] == "event_end":
                s7_observe.on_event_end(s, household_id, clock.parse(ev["at"]), now)
            accepted.append(eid)
    return {"accepted": accepted, "rejected": rejected, "plans_changed": plans_changed}


# ------------------------------------------------------------------------------------------ executions

def apply_execution(household_id: str, data: dict) -> dict:
    """POST /v1/hub/executions (body already checked against execution_result.json)."""
    from . import s7_observe

    with session_scope() as s:
        ep0 = s.get(Episode, data["plan_id"])
        if ep0 is None:
            raise HubInputError("not_found", "Unknown plan.")
        if ep0.household_id != household_id:
            raise HubInputError("forbidden", "This key belongs to another household.")
        lock_household(s, household_id)
        ep = s.execute(select(Episode).where(Episode.id == ep0.id).with_for_update()).scalar_one()
        now = clock.now()
        if s.get(Execution, data["result_id"]) is not None:
            return {"duplicate": True}
        plan = s.get(Plan, (ep.id, data["plan_version"]))
        if plan is None:
            raise HubInputError("not_found", "Unknown plan version.")
        task = s.get(Task, (ep.id, data["task_id"]))
        in_version = {t["task_id"]: t for t in plan.body["tasks"]}
        cancelled = {t["task_id"] for t in plan.body.get("cancelled", [])}
        if data["kind"] == "run":
            body = in_version.get(data["task_id"])
            if body is None or task is None:
                raise HubInputError("validation_error", "Not a task of that plan version.", "task_id")
            if not any(a["device"] == data["device"] and a["cmd"] == data["cmd"] for a in body["actions"]):
                raise HubInputError("validation_error", "Not an action of that task.", "device")
        else:
            if task is None or (data["task_id"] not in in_version and data["task_id"] not in cancelled):
                raise HubInputError("validation_error", "Not a task of that plan version.", "task_id")
            devices = {a["device"] for a in task.actions}
            for j, item in enumerate(data["items"]):
                if item["device"] not in devices:
                    raise HubInputError("validation_error", "Not a device of that task.", f"items[{j}].device")
        at = clock.parse(data["at"])
        s.add(Execution(result_id=data["result_id"], kind=data["kind"], operation_id=data.get("operation_id"),
                        plan_id=ep.id, plan_version=data["plan_version"], task_id=data["task_id"],
                        device=data.get("device"), cmd=data.get("cmd"), substrate=data.get("substrate"),
                        status=data.get("status"), reason=data.get("reason"), body=data, at=at, received_at=now))
        s.flush()
        if data["kind"] == "run":
            status = data["status"]
            meta = dict(task.meta or {})
            if status in ("running", "completed"):
                if task.started_at is None:
                    task.started_at = at
            elif status in ("failed", "unknown", "unverifiable") and task.started_at is None:
                meta["start_uncertain"] = True
                task.meta = meta
            started = status in ("running", "completed", "failed", "unknown")
            if task.status == "cancelled" and not task.restore and started and (task.end or {}).get("restore"):
                task.restore = True                                  # late start of a cancelled task (§11.3)
                dl = s.get(DeviceList, ep.household_id)
                s5_plan.publish(s, ep, now, dl.revision if dl else 0)
            if status in ("running", "completed") and task.source == "situation" and task.card_id:
                s7_observe.on_start(s, task, at)
        elif task.status == "live":
            task.status, task.ended_at = "ended", at               # the hub restored at the end
        refresh_task_lines(s, task, now)
    return {"duplicate": False}


def started(task: Task) -> bool:
    return task.started_at is not None or bool((task.meta or {}).get("start_uncertain"))


def ran_results(s: Session, task: Task) -> int:
    return len(s.execute(select(Execution.result_id).where(Execution.plan_id == task.episode_id,
                                                           Execution.task_id == task.task_id,
                                                           Execution.kind == "run")).all())
