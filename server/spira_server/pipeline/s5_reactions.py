"""Card reactions (spec §11.7, POST /v1/cards/{card_id}/reactions): stop, line_off, line_on. No LLM.

Every change takes the household lock first (§2.4), records `checked_changed_at`, touches the card (new seq,
notify false) and publishes a new plan version so the hub drops or gets the task."""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db.engine import lock_household, session_scope
from ..db.models import Card, CardLine, DeviceList, Episode, Task
from .s5_cards import card_body, touch
from .s5_plan import publish


class ReactionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def started(task: Task) -> bool:
    """§5.2: a confirmed start, or a start that may have happened."""
    return task.started_at is not None or bool((task.meta or {}).get("start_uncertain"))


def _cancel(task: Task) -> bool:
    if task.status not in ("live", "held"):
        return False
    task.status, task.restore = "cancelled", started(task)
    return True


def _held_card(card: Card) -> bool:
    return card.starts_at is None          # no time found for the card: its tasks wait as held (§11.6)


def react(card_id: str, reaction: str, task_id: str | None = None, *, now: datetime | None = None) -> dict:
    now = now or clock.now()
    with session_scope() as s:
        card = s.get(Card, card_id)
        if card is None:
            raise ReactionError("not_found", "Unknown card.")
        ep = s.get(Episode, card.episode_id)
        lock_household(s, ep.household_id)
        s.refresh(card)
        s.refresh(ep)
        if card.stopped:
            return card_body(s, card, now)
        rows = s.execute(select(CardLine, Task)
                         .join(Task, (Task.task_id == CardLine.task_id) & (Task.episode_id == card.episode_id))
                         .where(CardLine.card_id == card.id).order_by(CardLine.position)).all()
        changed = (_stop if reaction == "stop" else _line)(s, card, ep, rows, reaction, task_id, now)
        if changed:
            touch(s, card, now)
            dl = s.get(DeviceList, ep.household_id)
            publish(s, ep, now, dl.revision if dl else 0)
        return card_body(s, card, now)


def _stop(s: Session, card: Card, ep: Episode, rows, reaction, task_id, now: datetime) -> bool:
    for line, task in rows:
        if task.source == "situation":
            _cancel(task)
        line.state, line.checked_changed_at = "stopped", now
    card.stopped = True
    return True


def _line(s: Session, card: Card, ep: Episode, rows, reaction: str, task_id: str, now: datetime) -> bool:
    found = next(((ln, t) for ln, t in rows if ln.task_id == task_id), None)
    if found is None:
        raise ReactionError("not_found", "That task is not a line of this card.")
    line, task = found
    if reaction == "line_off":
        if not line.checked:
            return False
        _cancel(task)
        line.checked, line.state, line.checked_changed_at = False, "off", now
        return True
    if started(task):
        raise ReactionError("line_started", "The task already started.")
    if line.checked:
        return False
    slug = re.match(r"^t_([a-z][a-z0-9_]*)#\d+$", task.task_id).group(1)
    new_id = f"t_{slug}#{ep.next_task_n}"
    ep.next_task_n += 1
    held = _held_card(card)
    s.add(Task(episode_id=ep.id, task_id=new_id, card_id=card.id, source=task.source, way=task.way,
               status="held" if held else "live", need=task.need, line=task.line, actions=task.actions,
               trigger=task.trigger, end=task.end, target_room=task.target_room,
               end_after_start_minutes=task.end_after_start_minutes, meta=dict(task.meta or {})))
    position = line.position
    s.delete(line)
    s.flush()
    s.add(CardLine(card_id=card.id, task_id=new_id, position=position, checked=True,
                   state="held" if held else "scheduled", checked_changed_at=now))
    s.flush()
    return True
