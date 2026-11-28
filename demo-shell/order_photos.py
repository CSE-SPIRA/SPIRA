"""Order photos for the Server replay (README: Replay photos).

The SPIRA Server deletes order screenshots once S1 has read them, and the App keeps its own copy on the phone only.
So a replay has no photos unless the demo machine keeps them: this store holds the photos of an order shared
through the phone in the demo page, in memory only, and writes them to the demo machine's disk only when the
presenter keeps that run for the replay. Removing the run from the replay list deletes them.
"""

import os
import re
import shutil
import time
from pathlib import Path
from threading import Lock

EPISODE = re.compile(r"^ep_[0-9A-Za-z_]+$")
TYPES = {"image/jpeg": "jpg", "image/png": "png"}
HOLD_S = 24 * 3600          # photos of an order nobody kept are forgotten after a day
HOLD_MAX = 20               # and only the latest orders are held


def directory() -> Path:
    return Path(os.getenv("DEMO_PHOTOS_DIR") or Path(__file__).with_name("photos"))


class PhotoStore:
    def __init__(self, root: Path | None = None):
        self.root = root or directory()
        self.lock = Lock()
        self.held: dict[str, tuple[float, list[tuple[str, bytes]]]] = {}

    def hold(self, episode: str, photos: list[tuple[str, bytes]], now: float | None = None) -> None:
        """Remember an order's photos in memory (1-3 JPG or PNG)."""
        photos = [(kind, data) for kind, data in photos if kind in TYPES and data][:3]
        if not EPISODE.fullmatch(episode) or not photos:
            return
        now = time.time() if now is None else now
        with self.lock:
            old = self.held.get(episode)
            self.held[episode] = (now, ((old[1] if old else []) + photos)[:3])
            for key, (at, _) in list(self.held.items()):
                if now - at > HOLD_S:
                    del self.held[key]
            for key in sorted(self.held, key=lambda k: self.held[k][0])[:-HOLD_MAX]:
                del self.held[key]

    def keep(self, episode: str) -> int:
        """Write the held photos of a kept run to disk; returns how many."""
        if not EPISODE.fullmatch(episode):
            return 0
        with self.lock:
            held = self.held.pop(episode, None)
        if not held:
            return len(self.files(episode))
        folder = self.root / episode
        folder.mkdir(parents=True, exist_ok=True)
        for index, (kind, data) in enumerate(held[1], start=1):
            (folder / f"{index}.{TYPES[kind]}").write_bytes(data)
        return len(held[1])

    def drop(self, episode: str) -> None:
        """Forget a run's photos (removed from the replay list)."""
        if not EPISODE.fullmatch(episode):
            return
        with self.lock:
            self.held.pop(episode, None)
        shutil.rmtree(self.root / episode, ignore_errors=True)

    def files(self, episode: str) -> list[Path]:
        if not EPISODE.fullmatch(episode):
            return []
        folder = self.root / episode
        if not folder.is_dir():
            return []
        return sorted((p for p in folder.iterdir() if p.suffix[1:] in TYPES.values()), key=lambda p: p.name)
