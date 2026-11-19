"""`LLM_PROVIDER=mock` (spec §6.1): recorded outputs at `{dir}/{stage}/{key}.json`.

key = SHA-256 of (system, user, SHA-256 of each image). An unknown key raises `MockMissing`: tests record outputs
explicitly with `record(...)`. A file holds one of:

    {"output": {...}}          the JSON the model returned
    {"timeout": true}          the call timed out
    {"refusal": true}          the model refused
    {"text": "..."}            the model returned plain text
optionally with "usage": {"input": 100, "output": 20} and "note": "why this fixture exists".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..paths import LLM_FIXTURES_DIR
from .client import LLMTimeout, RawReply


class MockMissing(LookupError):
    pass


def key_for(system: str, user: str, images: Sequence[bytes] = ()) -> str:
    h = hashlib.sha256()
    h.update(system.encode("utf-8"))
    h.update(b"\n\x1e\n")
    h.update(user.encode("utf-8"))
    h.update(b"\n\x1e\n")
    h.update(",".join(hashlib.sha256(i).hexdigest() for i in images).encode())
    return h.hexdigest()[:32]


def record(folder: Path, stage: str, system: str, user: str, images: Sequence[bytes] = (), *,
           output: Any = None, timeout: bool = False, refusal: bool = False, text: str | None = None,
           note: str = "", usage: dict | None = None) -> Path:
    body: dict[str, Any] = {"note": note} if note else {}
    if timeout:
        body["timeout"] = True
    elif refusal:
        body["refusal"] = True
    elif text is not None:
        body["text"] = text
    else:
        body["output"] = output
    if usage:
        body["usage"] = usage
    path = Path(folder) / stage / f"{key_for(system, user, images)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class MockProvider:
    name = "mock"

    def __init__(self, folder: Path | str = LLM_FIXTURES_DIR, model: str = "mock") -> None:
        self.folder = Path(folder)
        self.model = model
        self.seen: list[tuple[str, str]] = []   # (stage, key) of every call, for tests

    def complete(self, *, stage: str, system: str, user: str, json_schema: dict, schema_name: str,
                 images: Sequence[bytes], timeout_s: int) -> RawReply:
        key = key_for(system, user, images)
        self.seen.append((stage, key))
        path = self.folder / stage / f"{key}.json"
        if not path.exists():
            raise MockMissing(f"no recorded LLM output for stage {stage}: {path}")
        body = json.loads(path.read_text(encoding="utf-8"))
        usage = body.get("usage", {})
        if body.get("timeout"):
            raise LLMTimeout(f"mock timeout ({path.name})")
        return RawReply(
            data=body.get("output"), text=body.get("text"), refusal=bool(body.get("refusal")),
            input_tokens=usage.get("input", 0), output_tokens=usage.get("output", 0),
        )

    def calls(self, stage: str | None = None) -> int:
        return sum(1 for s, _ in self.seen if stage is None or s == stage)
