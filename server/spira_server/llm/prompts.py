"""Prompt files (spec §6.3). Loaded once; list placeholders are filled from `contracts/kb/*.json` and
`server/config` so prompts and the KB never drift. Placeholders are replaced with plain string replacement."""

from __future__ import annotations

from functools import cache

from ..config import get_config, load_yaml
from ..kb.lists import get_lists
from ..paths import PROMPTS_DIR


@cache
def text(name: str) -> str:
    """Raw prompt file (trailing newline removed)."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").rstrip("\n")


@cache
def blocks(name: str) -> dict:
    return load_yaml((PROMPTS_DIR / name).read_text(encoding="utf-8"))


def fill(template: str, **values: object) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def groups_text() -> str:
    return " / ".join(get_config().product_groups)


def tags_text() -> str:
    definitions = blocks("cal_tag_definitions.yaml")
    return "\n".join(f"{tag} · {definitions.get(tag, '')}".rstrip(" ·") for tag in get_lists().calendar_tags)


def intents_text() -> str:
    return "\n".join(f"{i.id} · {i.name} · {i.definition}" for i in get_lists().intents)


@cache
def system(stage: str) -> str:
    """System prompt with its lists filled in."""
    if stage == "s1":
        return fill(text("s1_system.txt"), GROUPS=groups_text())
    if stage == "retype":
        return fill(text("retype_system.txt"), GROUPS=groups_text())
    if stage == "cal":
        return fill(text("cal_system.txt"), TAGS=tags_text())
    if stage == "s3":
        return fill(text("s3_system.txt"), INTENTS=intents_text())
    if stage == "s4":
        return text("s4_system.txt")
    raise ValueError(f"unknown stage {stage}")


def clear_cache() -> None:
    for f in (text, blocks, system):
        f.cache_clear()
