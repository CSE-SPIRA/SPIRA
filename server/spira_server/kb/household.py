"""Household type check (spec §12.3). Port of SPIRA_KB `spira/household.py` `rule_level`; the installed
`spira-kb` package does not ship `config/lists`, so the lists come from `contracts/kb/household_types.json`."""

from __future__ import annotations

from .lists import KbLists, get_lists


def min_people(t: set[str], lists: KbLists | None = None) -> int:
    hh = (lists or get_lists()).household
    n = (2 if "부부·커플" in t else 1) + sum(c in t for c in hh["child_types"]) + (1 if "부모 + 성인 자녀" in t else 0)
    return max(n, 3) if "3대 함께" in t else n


def rule_level(types: list[str], lists: KbLists | None = None) -> str | None:
    """'blocked' / 'rare' / None."""
    hh = (lists or get_lists()).household
    t = set(types)
    size = next((s for s in hh["axes"]["size"]["types"] if s in t), None)
    kids = {c for c in hh["child_types"] if c in t}
    need, cap = min_people(t, lists), hh["size_max"].get(size)
    if cap is not None and need > cap:
        return "blocked"
    if "룸메이트·셰어하우스" in t and (t & {"부부·커플", "부모 + 성인 자녀", "3대 함께"} or kids):
        return "blocked"
    if "맞벌이" in t and "부부·커플" not in t:
        return "blocked"
    if "은퇴·노년" in t and t & {"맞벌이", "재택근무"}:
        return "blocked"
    if "대학생" in t and ("맞벌이" in t or kids or "재택근무" in t):
        return "rare"
    if "은퇴·노년" in t and kids:
        return "rare"
    if {"1인": 1, "2인": 2, "3~4인": 3, "5인 이상": 5}.get(size, 1) - need >= 2:
        return "rare"
    return None


def check_types(types: list[str], lists: KbLists | None = None) -> str | None:
    """None if acceptable (rare is accepted); otherwise a reason for 422 household_types_invalid."""
    lists = lists or get_lists()
    known = set(lists.household_types)
    unknown = [x for x in types if x not in known]
    if unknown:
        return f"unknown household type: {', '.join(unknown)}"
    if len(set(types)) != len(types):
        return "duplicate household type"
    for axis, spec in lists.household["axes"].items():
        if spec["pick"] == "one" and sum(x in spec["types"] for x in types) > 1:
            return f"pick one {axis}"
    if rule_level(types, lists) == "blocked":
        return "blocked combination"
    return None
