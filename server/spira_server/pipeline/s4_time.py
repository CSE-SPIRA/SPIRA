"""find_time (spec §10.3): the LLM never makes times.

    calendar window -> holiday calendar -> this home's habit -> None (run tasks become held)

Every result satisfies start > now and end > start; a window that fails is skipped and the next step is tried.
`unclassified` bundles use the first two steps only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import Config
from ..db.models import Card, Case, Window
from ..kb.lists import KbLists


@dataclass(frozen=True)
class When:
    start: datetime
    end: datetime
    source: str            # calendar / holiday / habit

    def ok(self, now: datetime) -> bool:
        return self.start > now and self.end > self.start


def same_intent(intent_id: str, tags_a: list[str], tags_b: list[str]) -> bool:
    """Same intent id and (both tag lists empty, or they share a tag) (spec §1, §10.2)."""
    return (not tags_a and not tags_b) or bool(set(tags_a) & set(tags_b))


def find_time(s: Session, *, household_id: str, bundle: dict, shared_at: datetime, now: datetime, cfg: Config,
              lists: KbLists) -> When | None:
    window = bundle.get("use_window")
    if window:
        w = When(clock.parse(window["start"]), clock.parse(window["end"]), "calendar")
        if w.ok(now):
            return w
    holiday = holiday_time(bundle["intent_id"], shared_at, now, cfg, lists)
    if holiday:
        return holiday
    if bundle["intent_id"] == "unclassified":
        return None
    return habit_time(s, household_id=household_id, intent_id=bundle["intent_id"],
                      tags=bundle.get("calendar_tags") or [], shared_at=shared_at, now=now, cfg=cfg)


def _at(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=clock.KST)


def holiday_time(intent_id: str, shared_at: datetime, now: datetime, cfg: Config, lists: KbLists) -> When | None:
    intent = lists.intent(intent_id)
    if intent is None:
        return None
    shared_day = shared_at.astimezone(clock.KST).date()
    found: list[When] = []
    for tag in intent.related_tags:
        entry = cfg.holiday_calendar.get(tag)
        if not entry:
            continue
        for d in entry["days"]:
            day = d if isinstance(d, date) else date.fromisoformat(str(d))
            if not 0 <= (day - shared_day).days <= cfg.numbers.calendar_window_d:
                continue
            w = When(_at(day, entry["window"][0]), _at(day, entry["window"][1]), "holiday")
            if w.ok(now):
                found.append(w)
    return min(found, key=lambda w: w.start) if found else None


def occasion_starts(s: Session, household_id: str, intent_id: str, tags: list[str]) -> list[tuple[datetime, datetime]]:
    """(occasion start, row created_at) of same-intent `match` rows; start = windows.scheduled_start of the window
    that wrote the row (found by episode and card ordinal from case_id)."""
    rows = s.execute(select(Case).where(Case.source == "this_home", Case.household_id == household_id,
                                        Case.intent_id == intent_id, Case.verdict == "match")).scalars().all()
    out = []
    for row in rows:
        if not same_intent(intent_id, tags, list(row.when.get("calendar_tags") or [])):
            continue
        episode_id, ordinal = _parse_case_id(row.case_id, household_id)
        if episode_id is None:
            continue
        start = s.execute(
            select(Window.scheduled_start).join(Card, Card.id == Window.card_id)
            .where(Card.episode_id == episode_id, Card.ordinal == ordinal)
        ).scalar_one_or_none()
        if start is not None:
            out.append((start.astimezone(clock.KST), row.created_at))
    return out


def _parse_case_id(case_id: str, household_id: str) -> tuple[str | None, int]:
    prefix = f"home_{household_id}_"
    if not case_id.startswith(prefix):
        return None, 0
    episode_part, _, n = case_id[len(prefix):].rpartition("_")
    return (episode_part, int(n)) if n.isdigit() else (None, 0)


def habit_time(s: Session, *, household_id: str, intent_id: str, tags: list[str], shared_at: datetime,
               now: datetime, cfg: Config) -> When | None:
    starts = occasion_starts(s, household_id, intent_id, tags)
    return habit_from_starts(starts, shared_at, now, cfg)


def habit_from_starts(starts: list[tuple[datetime, datetime]], shared_at: datetime, now: datetime,
                      cfg: Config) -> When | None:
    n = cfg.numbers
    slot_min = n.habit_slot_h * 60
    rows = sorted(starts, key=lambda r: (r[0].weekday(), r[0].hour * 60 + r[0].minute))
    slots: list[list[tuple[datetime, datetime]]] = []
    for r in rows:
        first = slots[-1][0][0] if slots else None
        if (first is not None and first.weekday() == r[0].weekday()
                and abs(_minute(r[0]) - _minute(first)) <= slot_min):
            slots[-1].append(r)
        else:
            slots.append([r])
    candidates = [sl for sl in slots if len(sl) >= n.habit_min]
    if not candidates:
        return None
    best = sorted(candidates, key=lambda sl: (-len(sl), -max(c for _, c in sl).timestamp(), sl[0][0].weekday()))[0]
    minutes = sorted(_minute(st) for st, _ in best)
    median = minutes[(len(minutes) - 1) // 2]                     # lower median for even counts
    weekday = best[0][0].weekday()
    shared_day = shared_at.astimezone(clock.KST).date()
    day = now.astimezone(clock.KST).date()
    for _ in range(15):
        if day.weekday() == weekday:
            start = datetime.combine(day, time(median // 60, median % 60), tzinfo=clock.KST)
            if start > now and (day - shared_day).days <= n.calendar_window_d:
                return When(start, start + timedelta(hours=3), "habit")
        day += timedelta(days=1)
    return None


def _minute(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute
