"""Wall-clock scheduling for the committed live scene templates."""

from datetime import datetime, timedelta, timezone
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from spira_contracts.calendar import Calendar
from spira_contracts.card import Card
from spira_contracts.plan import Plan

from .observation import SEOUL
from .replay import CONTRACTS, Replay

WEEKDAYS = "월화수목금토일"


class NextOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    episode_id: Literal["ep_9031", "ep_9150", "ep_9120"]
    starts_in_seconds: int = Field(default=65, ge=1, le=3600)
    duration_seconds: int = Field(default=30, ge=1, le=3600)


def scene_times(order: NextOrder, now: datetime):
    starts = now + timedelta(seconds=order.starts_in_seconds)
    return starts, starts + timedelta(seconds=order.duration_seconds)


def server_numbers():
    return yaml.safe_load((CONTRACTS.parent / "server/config/numbers.yaml").read_text(encoding="utf-8"))


def substitute(value, replacements: dict[str, str]):
    if isinstance(value, dict):
        return {key: substitute(entry, replacements) for key, entry in value.items()}
    if isinstance(value, list):
        return [substitute(entry, replacements) for entry in value]
    return replacements.get(value, value) if isinstance(value, str) else value


def schedule_templates(
    replay: Replay, plan_name: str, card_name: str,
    starts: datetime, ends: datetime, *, demo_mode: bool, guest_window: int | None = None,
):
    numbers = server_numbers()
    offsets = numbers["demo"] if demo_mode else numbers
    replay.observation_window.scheduled_start = starts
    replay.observation_window.end_due = ends + timedelta(minutes=offsets["end_fallback_min"])
    replay.observation_window.guest_lead = timedelta(minutes=offsets["guest_window_before_min"])
    card = replay.load(Card, card_name)
    source_start = datetime.fromisoformat(card.starts_at)
    source_end = next(
        datetime.fromisoformat(event.end) for event in replay.calendar.events
        if datetime.fromisoformat(event.start) == source_start
    )
    timestamps = {
        source_start: starts,
        source_end: ends,
    }
    for name, old_anchor, new_anchor, sign in (
        ("guest_window_before_min", source_start, starts, -1),
        ("before_start_default_min", source_start, starts, -1),
        ("end_fallback_min", source_end, ends, 1),
    ):
        timestamps[old_anchor + timedelta(minutes=sign * numbers[name])] = (
            new_anchor + timedelta(minutes=sign * offsets[name])
        )
    replacements = {old.isoformat(): new.isoformat() for old, new in timestamps.items()}
    for name in (plan_name, card_name):
        replay.files[name] = substitute(replay.files[name], replacements)
    if demo_mode and guest_window is not None:
        closes = starts + timedelta(seconds=guest_window)
        window = {"from": starts.isoformat(), "to": closes.isoformat()}
        for task in replay.files[plan_name]["tasks"]:
            if task["trigger"].get("event") != "guest_arrived":
                continue
            task["trigger"]["window"] = window
            fallback = task["end"].get("or_time")
            if fallback and datetime.fromisoformat(fallback) <= closes:
                task["end"]["or_time"] = (closes + (ends - starts)).isoformat()


def rebase_linked_calendar(replay: Replay, starts: datetime, ends: datetime, shared: datetime):
    starts, ends, shared = (value.astimezone(SEOUL) for value in (starts, ends, shared))
    source_start = datetime.fromisoformat(replay.card.starts_at).astimezone(SEOUL)
    weekday = WEEKDAYS[starts.weekday()]
    original_day = f"{WEEKDAYS[source_start.weekday()]}요일"
    new_day = f"{weekday}요일"
    rationale = replay.files.get("rationale.json", {})
    for event in replay.files["calendar.json"]["events"]:
        if datetime.fromisoformat(event["start"]) != source_start:
            continue
        # Sub-minute rehearsal windows are too short for minute-level calendar evidence.
        calendar_end = ends if ends - starts >= timedelta(minutes=1) else (
            starts + (datetime.fromisoformat(event["end"]) - source_start)
        )
        event.update(start=starts.isoformat(), end=calendar_end.isoformat())
        for evidence in rationale.get("evidence", {}).get("calendar", []):
            if evidence["id"] == event["id"]:
                evidence.update(
                    days_after=(starts.date() - shared.date()).days, day=weekday,
                    start=starts.strftime("%H:%M"), end=calendar_end.strftime("%H:%M"),
                )
        break
    replay.calendar = replay.load(Calendar, "calendar.json")
    card = replay.files["card.v1.json"]
    card["text"] = card["text"].replace(original_day, new_day)
    for item in replay.episode.item_tasks:
        if item.text:
            item.text = item.text.replace(original_day, new_day)
    for item in rationale.get("item_tasks", []):
        if item.get("text"):
            item["text"] = item["text"].replace(original_day, new_day)


def live_replay(
    order: NextOrder, *, demo_mode: bool, now: datetime | None = None,
    sequence: int = 1, guest_window: int | None = None,
):
    now = now if now is not None else datetime.now(timezone.utc)
    replay = Replay(order.episode_id)
    if sequence > 1:
        identifiers = {order.episode_id: f"{order.episode_id}{sequence}"}
        if replay.card:
            card_id = replay.card.card_id
            identifiers[card_id] = f"{card_id}{sequence}"

        replay.files = substitute(replay.files, identifiers)
        replay.episode = replay.episode.model_copy(update={
            "episode_id": identifiers[order.episode_id],
            "card_ids": [identifiers[card_id] for card_id in replay.episode.card_ids],
        })
    if replay.card and replay.card.starts_at:
        starts, ends = scene_times(order, now)
        schedule_templates(
            replay, "plan.v1.json", "card.v1.json", starts, ends,
            demo_mode=demo_mode, guest_window=guest_window,
        )
        if demo_mode:
            rebase_linked_calendar(replay, starts, ends, now)
    plan = replay.files["plan.v1.json"]
    plan["sent_at"] = now.isoformat()
    if demo_mode:
        notice_after = server_numbers()["demo"]["notice_after_door_min"]
        item_tasks = {item.task_id: item for item in replay.episode.item_tasks}
        for task in plan["tasks"]:
            if task["end"].get("on") == "fridge.door_opened":
                task["end"]["after"] = f"{notice_after}m"
            item = item_tasks.get(task["task_id"])
            if task["source"] == "item" and item and item.item:
                for action in task["actions"]:
                    if action["cmd"] == "show_notice":
                        action["value"] = f"{item.item} · {item.text or action['value']}"
    replay.live = True
    replay.clock = now
    replay.set_plan(replay.load(Plan, "plan.v1.json"))
    if replay.card:
        card_name = "card.v1.json" if "card.v1.json" in replay.files else "card.held.json"
        card = replay.load(Card, card_name)
        summary = card.summary.model_copy(update={"waiting_for": replay.waiting_for(card.lines)})
        replay.card = card.model_copy(update={"updated_at": now.isoformat(), "summary": summary})
    replay.episode = replay.episode.model_copy(update={"shared_at": now.isoformat()})
    return replay


def scene_calendar(replay: Replay, order: NextOrder, now: datetime):
    if replay.card.starts_at and order.episode_id == "ep_9031":
        starts = datetime.fromisoformat(replay.card.starts_at)
        ends = starts + timedelta(seconds=order.duration_seconds)
    else:
        starts, ends = scene_times(order, now)
    first = replay.calendar.events[0]
    original_start = datetime.fromisoformat(first.start)
    shift = starts - original_start
    events = [first.model_copy(update={"start": starts.isoformat(), "end": ends.isoformat()})]
    for event in replay.calendar.events[1:]:
        start = datetime.fromisoformat(event.start) + shift
        end = datetime.fromisoformat(event.end) + shift
        events.append(event.model_copy(update={"start": start.isoformat(), "end": end.isoformat()}))
    return Calendar(events=events)


def apply_scene_calendar(
    replay: Replay, order: NextOrder, calendar: Calendar, *, demo_mode: bool, now: datetime | None,
    guest_window: int | None = None,
):
    if order.episode_id != "ep_9120" or replay.calendar_applied or replay.paused:
        return
    if not any(line.when is None and line.checked for line in replay.card.lines):
        return
    if [(event.id, event.title) for event in calendar.events] != [
        (event.id, event.title) for event in replay.calendar.events
    ]:
        return
    now = now if now is not None else datetime.fromisoformat(replay.tick())
    if calendar == replay.calendar:
        calendar = scene_calendar(replay, order, now)
    event = calendar.events[0]
    schedule_templates(
        replay, "plan.v2.json", "card.found.json",
        datetime.fromisoformat(event.start), datetime.fromisoformat(event.end),
        demo_mode=demo_mode, guest_window=guest_window,
    )
    replay.files["plan.v2.json"]["sent_at"] = now.isoformat()
    replay.find_calendar_time()
