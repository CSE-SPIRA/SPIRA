"""Call log (spec §15): one `llm_calls` row per stage call. A failed write is logged, never raised."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import Usage

log = logging.getLogger(__name__)


def record(*, stage: str, episode_id: str | None, provider: str, model: str, usage: Usage, attempts: int,
           outcome: str) -> None:
    try:
        from ..db.engine import session_scope
        from ..db.models import LlmCall

        with session_scope() as s:
            s.add(LlmCall(episode_id=episode_id, stage=stage, provider=provider, model=model,
                          input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                          latency_ms=usage.latency_ms, attempts=attempts, outcome=outcome))
    except Exception:
        log.exception("could not write llm_calls row")
