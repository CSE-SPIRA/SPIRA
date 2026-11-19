"""KB lists from `contracts/kb/*.json` (intents, calendar tags, household types). Read once at start."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..paths import KB_LISTS_DIR


@dataclass(frozen=True)
class Intent:
    id: str
    name: str
    definition: str
    group: str
    related_tags: tuple[str, ...]


@dataclass(frozen=True)
class KbLists:
    intents: tuple[Intent, ...]
    calendar_tags: tuple[str, ...]
    everyday_tags: frozenset[str]
    household: dict

    def intent(self, intent_id: str) -> Intent | None:
        return next((i for i in self.intents if i.id == intent_id), None)

    def intent_name(self, intent_id: str) -> str:
        if intent_id == "none":
            return "의도 없음"
        found = self.intent(intent_id)
        return found.name if found else intent_id

    @property
    def intent_ids(self) -> list[str]:
        return [i.id for i in self.intents]

    @property
    def household_types(self) -> list[str]:
        return [t for axis in self.household["axes"].values() for t in axis["types"]]


def load_lists(folder: Path = KB_LISTS_DIR) -> KbLists:
    def read(name: str) -> dict:
        return json.loads((folder / name).read_text(encoding="utf-8"))

    intents = read("intents.json")
    tags = read("calendar_tags.json")
    return KbLists(
        intents=tuple(
            Intent(i["id"], i["name"], i["definition"], i.get("group", ""), tuple(i.get("related_tags", [])))
            for i in intents["intents"]
        ),
        calendar_tags=tuple(t["tag"] for t in tags["tags"]),
        everyday_tags=frozenset(t["tag"] for t in tags["tags"] if t.get("everyday")),
        household=read("household_types.json"),
    )


@lru_cache(maxsize=1)
def get_lists() -> KbLists:
    return load_lists()
