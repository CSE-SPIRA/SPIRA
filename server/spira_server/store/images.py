"""Temporary order screenshots (spec §5.1 episode_images, §7). Files live in IMAGE_DIR until their pass is stored."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from ..settings import get_settings

log = logging.getLogger(__name__)

PNG = b"\x89PNG\r\n\x1a\n"
JPEG = b"\xff\xd8\xff"


def image_kind(data: bytes) -> str | None:
    if data.startswith(PNG):
        return "png"
    if data.startswith(JPEG):
        return "jpg"
    return None


def save(episode_id: str, data: bytes) -> str:
    kind = image_kind(data) or "bin"
    folder = Path(get_settings().image_dir) / episode_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.{kind}"
    path.write_bytes(data)
    return str(path)


def load(path: str) -> bytes:
    return Path(path).read_bytes()


def delete(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        log.warning("could not delete image %s", path)
