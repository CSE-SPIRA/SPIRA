"""Small builders shared by tests."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from spira_server.api.auth import new_hub_key
from spira_server.db.engine import session_scope
from spira_server.db.models import Household

DATA = Path(__file__).parent / "data"
FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


def png(seed: int = 0) -> bytes:
    """A valid 1x1 PNG; different seeds give different bytes (and different mock keys)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"\x00" + bytes([seed % 256, (seed // 256) % 256, 7])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def household(hid: str = "h_042", types: list[str] | None = None, paused: bool = False) -> str:
    with session_scope() as s:
        s.add(Household(id=hid, household_types=types if types is not None else ["3~4인", "영유아 자녀", "맞벌이"],
                        paused=paused, hub_key_hash=new_hub_key()[1]))
    return hid


def data(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def fixture(path: str) -> dict:
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))
