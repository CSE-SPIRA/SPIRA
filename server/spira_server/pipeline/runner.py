"""Pipeline after S1 (spec §2.4): S2 -> S3 -> S4 -> S5, each stage committing its result and `episodes.stage`.

    after_s1(episode_id)   S1 stored items for an episode that was not judged yet
    resume()               on start: finish every episode whose stage is s1 or s2 (no unread images left)

LLM and KB calls run outside any lock; S5 re-reads the household under its lock before confirming.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from ..db.engine import session_scope
from ..db.models import Episode, EpisodeImage
from . import s2_context, s3_intent, s4_tasks, s5_plan

log = logging.getLogger(__name__)


def after_s1(episode_id: str) -> None:
    run_from_s2(episode_id)


def run_from_s2(episode_id: str) -> None:
    if not s2_context.run(episode_id):
        return
    s3_intent.run(episode_id)
    drafts = s4_tasks.generate(episode_id)
    s5_plan.finalize(episode_id, drafts)


def resume() -> list[str]:
    """Episodes left mid-pipeline by a restart: stage s1/s2, still reading, no unread images (spec §2.3)."""
    with session_scope() as s:
        rows = s.execute(select(Episode.id).where(Episode.stage.in_(("s1", "s2")), Episode.status == "reading",
                                                  Episode.judged.is_(False))).scalars().all()
        waiting = set(s.execute(select(EpisodeImage.episode_id).where(EpisodeImage.read.is_(False))).scalars())
    todo = [e for e in rows if e not in waiting]
    for episode_id in todo:
        try:
            run_from_s2(episode_id)
        except Exception:  # noqa: BLE001 - one bad episode must not stop the others
            log.exception("resume failed for %s", episode_id)
    return todo
