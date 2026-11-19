"""Pipeline stages after S1 (spec §2.4). S2–S5 register themselves here as they are added; until then an episode
stops after S1 with `stage = s1`.

    after_s1(episode_id)   S1 stored items for an episode that was not judged yet -> run S2..S5
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

next_steps: list[Callable[[str], None]] = []


def after_s1(episode_id: str) -> None:
    if not next_steps:
        log.info("episode %s: items stored; S2-S5 not installed yet", episode_id)
    for step in next_steps:
        step(episode_id)
