"""KB search (spec §8.4): up to `search_limit` synthetic cases by cosine similarity, versions cumulative, KB_SAMPLE."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger(__name__)


class KbUnavailable(RuntimeError):
    """The KB DB failed twice (spec §8.6: episode judged with error.stage = s2)."""


@dataclass
class KbCase:
    case_id: str
    items: list[str]
    intent_id: str
    intent_text: str | None
    situation: dict
    when: dict
    household: dict
    sim: float


def in_sample(case_id: str, sample: float) -> bool:
    """Same rule as the SQL filter: first 8 hex digits of sha256(case_id) / 2^32 < sample."""
    return sample >= 1.0 or int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) < sample * 2**32


SQL = """
SELECT case_id, items, intent_id, intent_text, situation, "when", household,
       1 - (basket_emb <=> CAST(:q AS vector)) AS sim
FROM cases
WHERE source = 'synthetic'
  AND substring(kb_version from '^kb-v([0-9]+)$')::int <= :kb_version_number
  AND (:sample >= 1.0 OR ('x' || substr(encode(sha256(convert_to(case_id, 'UTF8')), 'hex'), 1, 8))::bit(32)::bigint
                          < :sample * 4294967296)
ORDER BY basket_emb <=> CAST(:q AS vector)
LIMIT :limit
"""


def _vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def search(engine: Engine, q: list[float], *, kb_version_number: int, sample: float, limit: int) -> list[KbCase]:
    """Retry once on a DB error, then raise KbUnavailable."""
    last: Exception | None = None
    for _ in range(2):
        try:
            return _search_once(engine, q, kb_version_number, sample, limit)
        except SQLAlchemyError as e:
            last = e
            log.warning("KB search failed: %s", e)
    raise KbUnavailable(str(last))


def _search_once(engine: Engine, q: list[float], version: int, sample: float, limit: int) -> list[KbCase]:
    with engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL statement_timeout = '15s'"))
        conn.execute(text(f"SET LOCAL hnsw.ef_search = {max(limit, 40)}"))
        iterative = _pgvector_at_least(conn, (0, 8))
        if iterative:
            conn.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        params: dict[str, Any] = {"q": _vector_literal(q), "kb_version_number": version, "sample": sample,
                                  "limit": limit if iterative else max(limit, 1000)}
        rows = conn.execute(text(SQL), params).mappings().all()
    cases = [KbCase(r["case_id"], list(r["items"]), r["intent_id"], r["intent_text"], r["situation"] or {},
                    r["when"] or {}, r["household"] or {}, float(r["sim"])) for r in rows]
    return cases[:limit]


def _pgvector_at_least(conn, want: tuple[int, int]) -> bool:
    v = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar_one_or_none()
    if not v:
        return False
    major, minor = (int(x) for x in v.split(".")[:2])
    return (major, minor) >= want
