"""Config tables load, and DEMO_MODE=1 gives the exact demo values (T42, config part)."""

import pytest

from spira_server import clock
from spira_server.config import load_config


def test_normal_values():
    n = load_config(demo=False).numbers
    assert (n.quiet_s, n.before_start_default_min, n.end_fallback_min, n.notice_after_door_min) == (600, 90, 180, 120)
    assert n.quiet_hours == [22, 8]


def test_demo_values_exact():
    n = load_config(demo=True).numbers
    assert n.quiet_s == 30
    assert n.before_start_default_min == 3
    assert n.end_fallback_min == 10
    assert n.notice_after_door_min == 2
    assert n.guest_window_before_min == 1
    assert n.group_window_h == 8          # not in demo: unchanged


def test_durations_are_integers_in_their_unit():
    n = load_config(demo=False).numbers.as_dict()
    for key, value in n.items():
        if key.endswith(("_s", "_min", "_h", "_d")) and key != "none_min":   # none_min is a share
            assert isinstance(value, int), key


def test_tables_present():
    cfg = load_config(demo=False)
    assert len(cfg.product_groups) == 18
    assert cfg.command_policy["notice"] == ["show_notice"]
    assert [t["name"] for t in cfg.item_tasks["tasks"]] == ["fridge", "freeze", "styler", "shoes", "mattress"]


@pytest.mark.parametrize("minutes,text", [(120, "2h"), (720, "12h"), (2, "2m"), (90, "90m"), (60, "1h")])
def test_contract_duration(minutes, text):
    assert clock.duration(minutes) == text
    assert clock.parse_duration(text).total_seconds() == minutes * 60


def test_iso_has_offset_and_whole_seconds():
    dt = clock.parse("2026-10-15T12:00:08.123+00:00")
    assert clock.iso(dt) == "2026-10-15T21:00:08+09:00"
    assert clock.weekday_ko(dt) == "목"
