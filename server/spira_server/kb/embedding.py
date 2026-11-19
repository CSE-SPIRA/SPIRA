"""Basket embedding (KB-16). `EMBED_MODE=bge` wraps `spira.embedding` (BGE-M3, same function as the KB loader);
`EMBED_MODE=mock` gives deterministic fake vectors for tests (spec §3.1, §17).

Mock vectors: each item name gets a fixed random unit vector (seeded by its SHA-256); a basket is the normalised sum.
Baskets that share items are close, unrelated single items are near-orthogonal, equal names give cosine 1.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
import threading
from collections.abc import Sequence
from functools import lru_cache

from ..settings import get_settings

log = logging.getLogger(__name__)

DIM = 1024
_ready = threading.Event()
_failed: list[BaseException] = []


def _mode() -> str:
    return get_settings().embed_mode


def basket_text(items: Sequence[str]) -> str:
    """Same rule as spira.embedding.basket_text: names only, sorted, joined with ', '."""
    return ", ".join(sorted(n.strip() for n in items if n and n.strip()))


@lru_cache(maxsize=4096)
def _mock_item(name: str) -> tuple[float, ...]:
    rng = random.Random(int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:16], 16))
    v = [rng.gauss(0.0, 1.0) for _ in range(DIM)]
    norm = math.sqrt(sum(x * x for x in v))
    return tuple(x / norm for x in v)


def _mock_basket(items: Sequence[str]) -> list[float]:
    names = basket_text(items).split(", ") if basket_text(items) else []
    if not names:
        return [0.0] * (DIM - 1) + [1.0]
    total = [0.0] * DIM
    for n in names:
        for i, x in enumerate(_mock_item(n)):
            total[i] += x
    norm = math.sqrt(sum(x * x for x in total)) or 1.0
    return [x / norm for x in total]


def embed_baskets(baskets: Sequence[Sequence[str]]) -> list[list[float]]:
    if _mode() == "mock":
        return [_mock_basket(b) for b in baskets]
    from spira.embedding import embed_baskets as real  # spira-kb[embed]

    return real(baskets)


def embed_basket(items: Sequence[str]) -> list[float]:
    return embed_baskets([items])[0]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # both are unit vectors


def warm_up() -> None:
    """Load the model once (blocking). /health stays 503 until this finishes."""
    try:
        if _mode() != "mock":
            from spira.embedding import _model

            _model()
        _ready.set()
    except BaseException as e:
        _failed.append(e)
        log.exception("embedding model failed to load")


def warm_up_in_background() -> None:
    if _mode() == "mock":
        warm_up()
        return
    threading.Thread(target=warm_up, name="embed-warm-up", daemon=True).start()


def ready() -> bool:
    return _ready.is_set()


def reset() -> None:
    """Tests only."""
    _ready.clear()
    _failed.clear()
