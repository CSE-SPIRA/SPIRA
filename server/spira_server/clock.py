"""Server clock (Asia/Seoul aware). Tests and dry runs replace it with `set_now` / `frozen`."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

_source: Callable[[], datetime] | None = None


def now() -> datetime:
    if _source is not None:
        return _source().astimezone(KST)
    return datetime.now(KST)


def set_now(source: Callable[[], datetime] | datetime | None) -> None:
    """Fix the clock (datetime), drive it (callable), or reset it (None)."""
    global _source
    if isinstance(source, datetime):
        _source = MovableClock(source)
    else:
        _source = source


@contextmanager
def frozen(at: datetime) -> Iterator[MovableClock]:
    clock = MovableClock(at)
    previous = _source
    set_now(clock)
    try:
        yield clock
    finally:
        set_now(previous)


class MovableClock:
    """A fixed clock that tests can move forward."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> datetime:
        self.at = self.at + timedelta(**delta)
        return self.at


def parse(value: str) -> datetime:
    """ISO 8601 with offset -> aware datetime in KST."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"time without offset: {value}")
    return dt.astimezone(KST)


def iso(dt: datetime | None) -> str | None:
    """Serialise with +09:00 and whole seconds (COM-02)."""
    if dt is None:
        return None
    return dt.astimezone(KST).replace(microsecond=0).isoformat()


def weekday_ko(dt: datetime) -> str:
    return WEEKDAYS[dt.astimezone(KST).weekday()]


def duration(minutes: int) -> str:
    """Contract duration string: whole hours as {n}h, otherwise {n}m (e.g. 120 -> 2h, 2 -> 2m)."""
    if minutes > 0 and minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def parse_duration(value: str) -> timedelta:
    n, unit = int(value[:-1]), value[-1]
    return timedelta(hours=n) if unit == "h" else timedelta(minutes=n)
