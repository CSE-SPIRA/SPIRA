"""Loads `server/config/*.yaml` once (spec §4). `DEMO_MODE=1` replaces the values under `numbers.yaml` `demo:`."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .paths import CONFIG_DIR


def _load(name: str, folder: Path = CONFIG_DIR) -> Any:
    with open(folder / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


class Numbers:
    """Read-only view of numbers.yaml: `cfg.numbers.quiet_s` or `cfg.numbers["quiet_s"]`."""

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = dict(values)

    def __getattr__(self, key: str) -> Any:
        try:
            return self._values[key]
        except KeyError as e:
            raise AttributeError(f"numbers.yaml has no {key}") from e

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)


@dataclass(frozen=True)
class Config:
    numbers: Numbers
    label_table: dict
    sensitive_words: dict
    item_tasks: dict
    holiday_calendar: dict
    device_names: dict
    card_templates: dict
    material_courses: dict
    command_policy: dict
    demo: bool

    @property
    def product_groups(self) -> list[str]:
        """The 18 product groups, in label_table.yaml order."""
        return list(self.label_table["groups"].keys())


def load_config(demo: bool, folder: Path = CONFIG_DIR) -> Config:
    raw = _load("numbers.yaml", folder)
    overrides = raw.pop("demo", {}) or {}
    unknown = set(overrides) - set(raw)
    if unknown:
        raise ValueError(f"numbers.yaml demo: keys not in the main list: {sorted(unknown)}")
    if demo:
        raw.update(overrides)
    return Config(
        numbers=Numbers(raw),
        label_table=_load("label_table.yaml", folder),
        sensitive_words=_load("sensitive_words.yaml", folder),
        item_tasks=_load("item_tasks.yaml", folder),
        holiday_calendar=_load("holiday_calendar.yaml", folder),
        device_names=_load("device_names.yaml", folder),
        card_templates=_load("card_templates.yaml", folder),
        material_courses=_load("material_courses.yaml", folder),
        command_policy=_load("command_policy.yaml", folder),
        demo=demo,
    )


@lru_cache(maxsize=2)
def get_config(demo: bool | None = None) -> Config:
    if demo is None:
        from .settings import get_settings

        demo = get_settings().demo_mode
    return load_config(demo)
