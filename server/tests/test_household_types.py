"""T39 (rules): blocked combinations rejected, rare accepted; equals SPIRA_KB rule_level when it is importable."""

import itertools

import pytest

from spira_server.kb.household import check_types, rule_level
from spira_server.kb.lists import get_lists


@pytest.mark.parametrize("types,level", [
    (["3~4인", "영유아 자녀", "맞벌이", "부부·커플"], None),
    (["1인", "부부·커플"], "blocked"),
    (["2인", "룸메이트·셰어하우스", "부부·커플"], "blocked"),
    (["1인", "맞벌이"], "blocked"),
    (["2인", "은퇴·노년", "재택근무", "부부·커플"], "blocked"),
    (["1인", "대학생", "재택근무"], "rare"),
    (["5인 이상"], "rare"),
])
def test_rule_level(types, level):
    assert rule_level(types) == level


def test_check_types():
    assert check_types(["3~4인", "영유아 자녀", "맞벌이", "부부·커플"]) is None
    assert check_types(["5인 이상"]) is None                       # rare is accepted
    assert check_types(["1인", "부부·커플"]) == "blocked combination"
    assert check_types(["1인", "2인"]) == "pick one size"
    assert check_types(["대학생", "직장인"]) == "pick one life_stage"
    assert "unknown" in check_types(["외계인"])


def _combinations():
    axes = get_lists().household["axes"]
    singles = [[None, *axes[a]["types"]] for a in ("size", "life_stage")]
    many = [axes[a]["types"] for a in ("composition", "work_style")]
    subsets = [[c for r in range(len(m) + 1) for c in itertools.combinations(m, r)] for m in many]
    for size, stage, comp, work in itertools.product(*singles, *subsets):
        yield [t for t in (size, stage) if t] + list(comp) + list(work)


def test_same_as_spira_kb():
    kb = pytest.importorskip("spira.household", reason="SPIRA_KB not installed")
    n = 0
    for types in _combinations():
        assert rule_level(types) == kb.rule_level(types), types
        n += 1
    assert n > 10000


def test_same_as_contracts_check():
    """contracts/check/check.py has its own copy of the blocked rules (CI guard for fixtures); keep them equal."""
    import importlib.util

    from .factories import FIXTURES

    spec = importlib.util.spec_from_file_location("contracts_check", FIXTURES.parent / "check" / "check.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    if not hasattr(check, "household_problem"):
        pytest.skip("contracts/check without the household check")
    for types in _combinations():
        assert (check.household_problem(types) is None) == (check_types(types) is None), types
