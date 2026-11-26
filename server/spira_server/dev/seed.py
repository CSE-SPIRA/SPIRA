"""Fake home for dry runs and the demo (`server/dev/home.example.yaml`). Not used by the running server.

Writes the household, device list, calendar (tagged by the server LLM like a real PUT) and past orders straight into
the server DB with the same functions the S6 routes will use. Every run starts the household from scratch.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import delete

from .. import clock
from ..api.auth import new_hub_key
from ..config import load_yaml
from ..db.engine import session_scope
from ..db.models import Case, DeviceList, Episode, Household, OrderItem
from ..kb.household import check_types
from ..pipeline.s2_calendar import CalendarInput, receive_calendar, tag_events

RELATIVE = re.compile(r"^\+(\d+)d (\d{1,2}):(\d{2})$")


class HomeError(ValueError):
    pass


@dataclass
class Home:
    household_id: str
    household_types: list[str]
    devices: dict
    calendar: list[CalendarInput]
    past_orders: list[dict]


def when(value: str, now: datetime) -> str:
    """'+2d 14:00' -> ISO on (today + 2 days) 14:00 Asia/Seoul; an ISO string is kept."""
    m = RELATIVE.match(value.strip())
    if not m:
        return clock.iso(clock.parse(value))
    day: date = now.astimezone(clock.KST).date() + timedelta(days=int(m.group(1)))
    return clock.iso(datetime.combine(day, time(int(m.group(2)), int(m.group(3))), tzinfo=clock.KST))


def load_home(path: Path, now: datetime) -> Home:
    raw = load_yaml(path.read_text(encoding="utf-8"))
    hid = raw["household_id"]
    if not re.match(r"^h_[0-9a-z]+$", hid):
        raise HomeError(f"household_id {hid!r}: use h_ + lowercase letters/digits")
    types = list(raw.get("household_types") or [])
    problem = check_types(types)
    if problem:
        raise HomeError(f"household_types {types}: {problem} (kb/household_types.json rules)")
    devices: list[dict] = []
    base = raw.get("devices_from")
    if base:
        devices += json.loads((path.parent / base).read_text(encoding="utf-8"))["devices"]
    devices += raw.get("extra_devices") or []
    ids = [d["id"] for d in devices]
    if len(set(ids)) != len(ids):
        raise HomeError(f"device ids repeat: {ids}")
    missing_room = [d["id"] for d in devices if not d.get("room")]
    if missing_room:
        raise HomeError(f"devices without a room: {missing_room} (room-specific tasks would be dropped)")
    body = {"household_id": hid, "revision": int(raw.get("devices_revision", 1)), "devices": devices}
    calendar = [CalendarInput(str(e["id"]), e["title"], when(e["start"], now), when(e["end"], now))
                for e in raw.get("calendar") or []]
    return Home(hid, types, body, calendar, list(raw.get("past_orders") or []))


def reset(household_id: str) -> None:
    with session_scope() as s:
        s.execute(delete(Case).where(Case.household_id == household_id))
        s.execute(delete(Household).where(Household.id == household_id))       # cascades to episodes, plans, ...


def seed(home: Home, now: datetime, hub_key_hash: str | None = None) -> dict:
    """Returns what was written (for the run log). `hub_key_hash`: keep a key the caller made (the demo hub uses
    it); default a random key nobody knows (dry runs have no hub)."""
    reset(home.household_id)
    with session_scope() as s:
        s.add(Household(id=home.household_id, household_types=home.household_types, paused=False,
                        hub_key_hash=hub_key_hash or new_hub_key()[1]))
        s.flush()
        s.add(DeviceList(household_id=home.household_id, revision=home.devices["revision"], body=home.devices))
        for n, order in enumerate(home.past_orders):
            at = now - timedelta(days=int(order["days_ago"]))
            eid = f"ep_{home.household_id[2:]}p{n}"
            s.add(Episode(id=eid, household_id=home.household_id, status="closed", shared_at=at, received_at=at,
                          source_ids=[], judged=True, stage="done", plan_version=0, closed_at=at,
                          next_item_n=len(order["items"]) + 1, next_task_n=1, next_card_ordinal=1,
                          rerun_pending=False))
            s.flush()
            for k, item in enumerate(order["items"], start=1):
                s.add(OrderItem(episode_id=eid, id=f"it_{k}", name=item.get("name") or item["type"],
                                type=item["type"], grp=item.get("group"), label=item.get("label", "clue"),
                                qty=item.get("qty"), attributes=item.get("attributes") or [], masked=False))
    tagged = False
    if home.calendar:
        accepted = receive_calendar(home.household_id, home.calendar)
        tagged = tag_events(accepted)
    return {"household_id": home.household_id, "devices": len(home.devices["devices"]),
            "calendar": len(home.calendar), "calendar_tagged": tagged, "past_orders": len(home.past_orders)}
