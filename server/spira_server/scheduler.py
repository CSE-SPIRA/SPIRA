"""In-process jobs (spec §2.3, APScheduler). This PR has `quiet_timer`; the other jobs come with S5–S7.

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
