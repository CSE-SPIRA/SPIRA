"""Pipeline stages after S1 (spec §2.4): each stage commits its result and `episodes.stage`.

    after_s1(episode_id)   S1 stored items for an episode that was not judged yet -> S2 -> S3 -> (S4, S5)

S4–S5 register themselves in `next_steps`; until they exist an episode stops after S3 (`stage = s2`, intent stored).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from . import s2_context, s3_intent

log = logging.getLogger(__name__)

next_steps: list[Callable[[str], None]] = []


def after_s1(episode_id: str) -> None:
    if not s2_context.run(episode_id):
        return
    s3_intent.run(episode_id)
    if not next_steps:
        log.info("episode %s: intent stored; S4-S5 not installed yet", episode_id)
    for step in next_steps:
        step(episode_id)
