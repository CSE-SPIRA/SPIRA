"""Demo story clock (spec §12.6, contracts/openapi/demo.yaml). DEMO_MODE=1 only.

One clock per server process. The Hub (`SPIRA_DEMO_CLOCK_URL`), the Simulator (through the Hub's MQTT `P/clock`) and
the demo shell read the same anchors, and the server's own `clock.now()` follows it (`install`), so triggers,
windows and task ends all run on story time. Story time only moves forward: a ramp speeds it up for a few real
seconds, then it runs at 1× again. A demo reset (§12.5) puts it back on wall time.

    story now = story_at + (real now − real_at) × rate          until ramp_until
              = (where the ramp ended) + (real now − ramp_until) after it
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import clock


def _wall() -> datetime:
    return datetime.now(clock.KST)


@dataclass(frozen=True)
class State:
    version: int
    real_at: datetime
    story_at: datetime
    rate: float
    ramp_until: datetime | None

    def story(self, real_now: datetime) -> datetime:
        if self.ramp_until is not None and real_now > self.ramp_until:
            reached = self.story_at + (self.ramp_until - self.real_at) * self.rate
            return reached + (real_now - self.ramp_until)
        return self.story_at + (real_now - self.real_at) * self.rate


class StoryClock:
    def __init__(self, real: Callable[[], datetime] = _wall) -> None:
        self.real = real
        self._lock = threading.Lock()
        now = real()
        self.state = State(1, now, now, 1.0, None)

    def now(self) -> datetime:
        return self.state.story(self.real()).astimezone(clock.KST)

    def body(self) -> dict:
        st, real_now = self.state, self.real()
        return {"version": st.version, "real_at": _iso(st.real_at), "story_at": _iso(st.story_at),
                "rate": st.rate, "ramp_until": _iso(st.ramp_until) if st.ramp_until else None,
                "now": _iso(st.story(real_now))}

    def advance(self, target: datetime, over_seconds: float) -> dict:
        """Ramp to `target` over `over_seconds` real seconds. ValueError when target is not after story time."""
        with self._lock:
            real_now = self.real()
            current = self.state.story(real_now)
            if target <= current:
                raise ValueError("advance_to must be after story time now")
            self.state = State(self.state.version + 1, real_now, current,
                               (target - current).total_seconds() / over_seconds,
                               real_now + timedelta(seconds=over_seconds))
        return self.body()

    def to_wall(self) -> None:
        with self._lock:
            now = self.real()
            self.state = State(self.state.version + 1, now, now, 1.0, None)


def _iso(dt: datetime) -> str:
    """Milliseconds: a 4-second ramp must not round its anchors away."""
    return dt.astimezone(clock.KST).isoformat(timespec="milliseconds")


_clock: StoryClock | None = None


def get() -> StoryClock:
    global _clock
    if _clock is None:
        _clock = StoryClock()
    return _clock


def install() -> None:
    """Make `clock.now()` follow the story clock (server start with DEMO_MODE=1)."""
    clock.set_now(get().now)


def reset() -> None:
    """Back on wall time (demo reset, spec §12.5). No-op when no story clock was made."""
    if _clock is not None:
        _clock.to_wall()


def clear() -> None:
    """Tests only."""
    global _clock
    _clock = None
