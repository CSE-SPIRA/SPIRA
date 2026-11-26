"""In-process jobs (spec §2.3, APScheduler): `quiet_timer` per episode, and `end_tasks`, `close_windows`,
`close_episodes` together every 10 min (every 2 s with DEMO_MODE=1, so a story-clock ramp is followed at once).

When the scheduler is not running (tests, dry runs) jobs are only remembered in `pending`, and the caller runs them
itself (`s1_extract.on_quiet`).
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from .clock import KST

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
pending: dict[str, datetime] = {}       # job id -> run time, when not running


def start() -> None:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=KST, job_defaults={"misfire_grace_time": None, "coalesce": True})
        _scheduler.start()
        from .pipeline.s7_observe import run_jobs
        from .settings import get_settings

        every = 2 if get_settings().demo_mode else 600
        _scheduler.add_job(run_jobs, "interval", seconds=every, id="clock_jobs", replace_existing=True,
                           max_instances=1)
        for job_id, at in list(pending.items()):
            _add(job_id, at)
        pending.clear()


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def running() -> bool:
    return _scheduler is not None


def _add(job_id: str, at: datetime) -> None:
    kind, _, arg = job_id.partition(":")
    if kind == "quiet":
        from .pipeline.s1_extract import on_quiet

        _scheduler.add_job(on_quiet, "date", run_date=at, args=[arg], id=job_id, replace_existing=True)
    else:  # pragma: no cover
        raise ValueError(job_id)


def schedule_quiet(episode_id: str, at: datetime) -> None:
    """(Re)schedule the quiet timer of an episode; a newer capture replaces the older timer (spec §7.1 step 7)."""
    job_id = f"quiet:{episode_id}"
    if _scheduler is None:
        pending[job_id] = at
    else:
        _add(job_id, at)


def clear() -> None:
    """Tests only."""
    pending.clear()
