"""Local persistence for the observations and actions received by the demo shell."""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RECORDING_ID = re.compile(r"[0-9a-f]{32}")


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["share", "reaction", "house", "finish", "episode", "rationale", "cards",
                  "rationale_missing", "read_problem", "hub", "memory", "clock", "moments", "snapshot", "viewer",
                  "scene", "artwork", "presenter"]
    arrived_at: datetime
    story_at: datetime | None
    data: Any
    read: int | None = Field(default=None, ge=0)


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_id: str = Field(pattern=r"^ep_[A-Za-z0-9_]+$", max_length=100)
    household_id: str = Field(pattern=r"^h_[A-Za-z0-9_]+$", max_length=100)
    story_timing: dict[str, dict[str, int]] | None = None
    demo_path: Literal["house", "plan"] | None = None
    offset: int = Field(ge=0)
    entries: list[Entry] = Field(min_length=1, max_length=200)


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=100)
    starred: bool


def directory():
    return Path(os.getenv("DEMO_RECORDINGS_DIR") or Path(__file__).with_name("recordings"))


class RecordingStore:
    def __init__(self):
        self.lock = Lock()

    def path(self, recording_id):
        if not RECORDING_ID.fullmatch(recording_id):
            raise FileNotFoundError(recording_id)
        return directory() / f"{recording_id}.json"

    def read(self, recording_id):
        return json.loads(self.path(recording_id).read_text(encoding="utf-8"))

    def index(self):
        rows = []
        for path in directory().glob("*.json"):
            try:
                run = self.read(path.stem)
                rows.append({key: run[key] for key in
                             ("id", "episode_id", "created_at", "name", "starred", "complete")})
            except (OSError, ValueError, KeyError):
                continue
        return sorted(rows, key=lambda row: (row["starred"], row["created_at"], row["id"]), reverse=True)

    def latest_path(self, episode):
        match = max((row for row in self.index() if row["episode_id"] == episode),
                    key=lambda row: row["created_at"], default=None)
        return self.read(match["id"]).get("demo_path") if match else None

    def write(self, run):
        path = self.path(run["id"])
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as target:
            temp = Path(target.name)
            try:
                json.dump(run, target, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                target.close()
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)

    def append(self, recording_id, batch, tags=None):
        self.path(recording_id)
        with self.lock:
            try:
                run = self.read(recording_id)
            except FileNotFoundError:
                run = {
                    "version": 1, "id": recording_id, "episode_id": batch.episode_id,
                    "household_id": batch.household_id, "story_timing": batch.story_timing,
                    "demo_path": batch.demo_path,
                    "created_at": datetime.now(timezone.utc).isoformat(), "name": "", "starred": False,
                    "complete": False, "entries": [],
                }
            entries = run["entries"]
            if (run["episode_id"] != batch.episode_id or batch.offset > len(entries)
                    or run.get("demo_path") != batch.demo_path):
                raise ValueError("Recording entries are out of sequence")
            pending = batch.entries[len(entries) - batch.offset:]
            if pending or (tags and run.get("tags") != tags):
                entries.extend(entry.model_dump(mode="json") for entry in pending)
                run["complete"] = any(entry.kind == "finish" for entry in pending) or run["complete"]
                if tags and "arrived_at" in tags:
                    run["tags"] = tags
                self.write(run)
            return len(entries)

    def save_tags(self, recording_id, episode, tags):
        with self.lock:
            try:
                run = self.read(recording_id)
            except FileNotFoundError:
                return  # The first append attaches tags that arrived before the file.
            if run["episode_id"] == episode:
                run["tags"] = tags
                self.write(run)

    def label(self, recording_id, label):
        with self.lock:
            run = self.read(recording_id)
            run.update(name=label.name.strip(), starred=label.starred)
            self.write(run)
