"""Stage times (spec §2.4): the wall time each stage ended, in `episodes.stage_times`, for display and replay.

Keys: `received` (capture stored), `s1_start` (first S1 pass began), `s1`, `s2`, `s3`, `s4`, `s5`. Each is set inside
the transaction that stores that stage's result, so a reader never sees a time without its result. Wall time, not the
server clock: the demo clock may be moved while a judgment runs, and a replay needs real durations. A re-run (§14)
overwrites the keys it passes through.
"""

from __future__ import annotations

from datetime import datetime

from .. import clock
from ..db.models import Episode


def wall() -> datetime:
    return datetime.now(clock.KST)


def mark(ep: Episode, key: str, at: datetime | None = None) -> None:
    times = dict(ep.stage_times or {})
    times[key] = clock.iso_ms(at or wall())
    ep.stage_times = times                                   # new dict: JSONB changes are seen by the session
