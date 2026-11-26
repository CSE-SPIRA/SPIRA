"""S2 context (spec §8.1–8.4, §15): T8 T9 T10 T11 T57, ep_9031 evidence, switches, representative cases."""

from collections import Counter

import pytest
from sqlalchemy import text

from spira_server.db.engine import kb_engine, session_scope
from spira_server.db.models import Episode
from spira_server.kb import embedding
from spira_server.kb.search import in_sample, search
from spira_server.pipeline import runner, s2_context
from spira_server.pipeline.s2_context import pick_reps

from . import kb_seed
from .factories import fixture, household
from .s2_helpers import ITEMS, SHARED, ep9031, episode, history


@pytest.fixture
def kb(env):
    env(KB_MODE="on", KB_VERSION="kb-v1")
    kb_seed.clear()
    yield kb_seed
    kb_seed.clear()


def _unusual(ep: str) -> dict:
    return s2_context.build_context(ep)["for_intent"]["this_home"]["unusual_items"]


def test_order_time_always_present(env):
    env(HOME_CONTEXT="off")
    ep = ep9031()
    assert s2_context.build_context(ep) == {
        "for_intent": {"order_time": {"shared_at": "2026-10-15T21:00:08+09:00", "weekday": "목"}}, "snapshot": []}


def test_ep9031_this_home_matches_rationale_evidence():
    ep = ep9031()
    home = s2_context.build_context(ep)["for_intent"]["this_home"]
    evidence = fixture("ep_9031/rationale.json")["evidence"]
    assert home["household_types"] == ["3~4인", "부부·커플", "영유아 자녀", "맞벌이"]
    assert home["calendar"] == evidence["calendar"]           # c3 everyday-only, c4/c5 no tags: dropped
    got, want = home["unusual_items"], evidence["unusual_items"]
    assert got["status"] == want["status"] == "list"
    pairs = lambda rows: sorted((r["item"], r["why"]) for r in rows)  # noqa: E731
    assert pairs(got["items"]) == pairs(want["items"])
    assert got["usual"] == want["usual"]


def test_t8_insufficient():
    household()
    with session_scope() as s:
        history(s, n_orders=9)
        episode(s, "ep_9031", SHARED, ITEMS, status="reading")
    assert _unusual("ep_9031") == {"status": "insufficient"}


def test_t8_all_usual():
    household()
    with session_scope() as s:
        history(s, n_orders=12)
        episode(s, "ep_9031", SHARED, [("세탁 세제", 1, "clue"), ("로션", 1, "clue"), ("우유", 1, "care")],
                status="reading")
    assert _unusual("ep_9031") == {"status": "all_usual"}


def test_t8_similar_type_names_count_as_same(monkeypatch):
    household()
    with session_scope() as s:
        history(s, n_orders=12)
        episode(s, "ep_9031", SHARED, [("흰우유", 1, "care")], status="reading")
    real = embedding.cosine
    monkeypatch.setattr(embedding, "cosine", lambda a, b: 0.9 if a != b else real(a, b))
    assert _unusual("ep_9031") == {"status": "all_usual"}      # 흰우유 ~ 우유 (and 계란...) above type_sim


def test_masked_items_are_left_out():
    household()
    with session_scope() as s:
        history(s, n_orders=12)
        episode(s, "ep_9031", SHARED, [("우유", 1, "care")], status="reading")
        from spira_server.db.models import OrderItem
        s.add(OrderItem(episode_id="ep_9031", id="it_2", name=None, type=None, grp=None, label="clue", qty=1,
                        masked=True))
    assert _unusual("ep_9031") == {"status": "all_usual"}


def test_kb_neighbours_counts_and_examples(kb):
    kb.seed_birthday_neighbours()
    ep = ep9031()
    ctx = s2_context.build_context(ep)
    nb = ctx["for_intent"]["kb_neighbors"]
    assert nb["similar_count"] == 12 and nb["note"] is None
    assert nb["intent_counts"] == [                          # R48: share of the kept 12, base share of the KB 15
        {"intent_id": "kid_birthday_party", "name": "아이 생일 파티", "n": 9, "share": 0.75, "base_share": 0.6},
        {"intent_id": "home_baking", "name": "홈베이킹", "n": 2, "share": 0.1667, "base_share": 0.1333},
        {"intent_id": "none", "name": "의도 없음", "n": 1, "share": 0.0833, "base_share": 0.2667},
    ]
    assert nb["base_total"] == 15
    # 9/12 = 75 % < 80 % -> home baking added; none 1/12 = 8 % < 10 % -> not shown
    assert [e["intent_id"] for e in nb["examples"]] == ["kid_birthday_party", "home_baking"]
    ex = nb["examples"][0]
    assert set(ex) == {"case_id", "items", "intent_id", "intent_text", "situation", "calendar_tags",
                       "case_household_types"}       # R49: no exact-name overlap
    assert ex["calendar_tags"] == ["생일"]                    # the c1 tag bonus puts a tagged case first
    assert len(ctx["snapshot"]) == 12 and not any(c.startswith("syn_T9") for c in ctx["snapshot"])
    rec = ctx["kb_search"]                                   # display and replay only (§8.3 step 9)
    assert (rec["searched"], rec["sim_floor"], rec["used"]) == (len(rec["sims"]), 0.70, 12)
    assert rec["above_floor"] == sum(1 for x in rec["sims"] if x > 0.70) >= 12
    assert rec["sims"] == sorted(rec["sims"], reverse=True) and len(rec["top"]) == min(10, rec["searched"])
    assert [r["sim"] for r in rec["top"]] == rec["sims"][: len(rec["top"])]
    assert {r["case_id"] for r in rec["top"] if r["used"]} <= set(ctx["snapshot"])
    assert set(rec["top"][0]) == {"case_id", "sim", "score", "intent_id", "intent_text", "items", "used"}
    from spira_server.pipeline.s3_intent import build_intent_message
    items = [{"item_id": "it_1", "type": "딸기", "qty": 2, "attributes": []}]
    assert build_intent_message(ctx, items) == build_intent_message({"for_intent": ctx["for_intent"]}, items)


def test_t9_few_similar_cases(kb):
    for n in range(4):
        items = ["풍선", "케이크 토퍼", "고깔모자", "딸기", "아이싱 펜", "휘핑크림", f"x{n}"]
        kb.add(f"syn_F_{n:04d}", items, "kid_birthday_party")
    ep = ep9031()
    ctx = s2_context.build_context(ep)
    assert ctx["for_intent"]["kb_neighbors"] == {"similar_count": 4, "note": "비슷한 사례가 거의 없음"}
    assert ctx["snapshot"] == []
    assert ctx["kb_search"]["above_floor"] == 4 and ctx["kb_search"]["used"] == 0


def test_r48_floor_070_drops_cases_sharing_few_items(kb):
    """dry run B (11-21): 0.6 let in baskets sharing 0-1 items; 0.70 is about a third of the basket shared."""
    for n in range(6):                                     # 5 of 6 items shared: mock sim about 0.68
        kb.add(f"syn_L_{n:04d}", ["풍선", "케이크 토퍼", "고깔모자", "딸기", "아이싱 펜", f"y{n}"],
               "kid_birthday_party")
    nb = s2_context.build_context(ep9031())["for_intent"]["kb_neighbors"]
    assert nb == {"similar_count": 0, "note": "비슷한 사례가 거의 없음"}


def test_r48_none_row_and_base_rate(kb):
    kb.seed_birthday_neighbours()
    with kb.engine().begin() as conn:                      # the one similar none case leaves; dissimilar ones stay
        conn.execute(text("DELETE FROM cases WHERE case_id = 'syn_T3_0000'"))
    nb = s2_context.build_context(ep9031())["for_intent"]["kb_neighbors"]
    assert nb["intent_counts"][-1] == {"intent_id": "none", "name": "의도 없음", "n": 0, "share": 0.0,
                                       "base_share": round(3 / 14, 4)}
    assert sum(r["n"] for r in nb["intent_counts"]) == nb["similar_count"] == 11


def test_r48_base_rate_is_kept_then_counted_again(kb, monkeypatch):
    kb.seed_birthday_neighbours()
    ep = ep9031()
    now = [1000.0]
    monkeypatch.setattr(s2_context.time, "monotonic", lambda: now[0])
    assert s2_context.build_context(ep)["for_intent"]["kb_neighbors"]["base_total"] == 15
    kb.add("syn_N_0000", ["라면", "생수"], "none")
    now[0] += 59 * 60
    assert s2_context.build_context(ep)["for_intent"]["kb_neighbors"]["base_total"] == 15
    now[0] += 2 * 60                                       # base_refresh_min 60
    assert s2_context.build_context(ep)["for_intent"]["kb_neighbors"]["base_total"] == 16


def test_r48_base_rate_follows_version_and_sample(kb, env):
    kb.seed_birthday_neighbours()
    kb.add("syn_V2_0000", ["라면", "생수"], "none", kb_version="kb-v2")
    ep = ep9031()
    assert s2_context.build_context(ep)["for_intent"]["kb_neighbors"]["base_total"] == 15
    env(KB_VERSION="kb-v2")
    assert s2_context.build_context(ep)["for_intent"]["kb_neighbors"]["base_total"] == 16
    env(KB_VERSION="kb-v1", KB_SAMPLE="0.5")
    with kb.engine().connect() as conn:
        ids = [r[0] for r in conn.execute(text("SELECT case_id FROM cases WHERE kb_version = 'kb-v1'"))]
    want = sum(1 for i in ids if in_sample(i, 0.5))
    assert 0 < want < len(ids)
    from spira_server.config import get_config
    from spira_server.settings import get_settings
    assert sum(s2_context.base_rates(get_settings(), get_config().numbers).values()) == want


def test_home_context_off_drops_bonus_and_home(kb, env):
    kb.seed_birthday_neighbours()
    env(HOME_CONTEXT="off")
    ctx = s2_context.build_context(ep9031())
    assert "this_home" not in ctx["for_intent"]
    assert ctx["for_intent"]["kb_neighbors"]["similar_count"] == 12


def test_t10_kb_sample_nested_and_deterministic(kb):
    for n in range(150):
        kb.add(f"syn_S_{n:04d}", ["딸기", "풍선", f"a{n}", f"b{n % 7}"], "none")
    q = embedding.embed_basket(["딸기", "풍선"])

    def ids(sample):
        return {c.case_id for c in search(kb_engine(), q, kb_version_number=1, sample=sample, limit=200)}

    quarter, half, full = ids(0.25), ids(0.5), ids(1.0)
    assert quarter < half < full and len(full) == 150
    assert ids(0.25) == quarter
    assert quarter == {c for c in full if in_sample(c, 0.25)}     # SQL and Python rules agree


def test_t11_versions_are_cumulative(kb):
    for ver in ("kb-v1", "kb-v2", "kb-v3"):
        kb.add(f"syn_{ver}_0001", ["딸기", "풍선"], "none", kb_version=ver)
    q = embedding.embed_basket(["딸기", "풍선"])
    got = {c.case_id for c in search(kb_engine(), q, kb_version_number=2, sample=1.0, limit=200)}
    assert got == {"syn_kb-v1_0001", "syn_kb-v2_0001"}


def test_t57_kb_down_judged_with_error(env):
    env(KB_MODE="on", KB_DATABASE_URL="postgresql://spira:spira@localhost:1/nothing")
    ep = ep9031()
    runner.after_s1(ep)
    with session_scope() as s:
        e = s.get(Episode, ep)
        assert (e.status, e.judged, e.stage, e.error["stage"]) == ("judged", True, "done", "s2")
        assert e.intent["bundles"] == []


def test_run_stores_context():
    ep = ep9031()
    assert s2_context.run(ep) is True
    with session_scope() as s:
        e = s.get(Episode, ep)
        assert e.stage == "s2" and e.context["for_intent"]["order_time"]["weekday"] == "목"
        assert "kb_search" not in e.context and set(e.stage_times) == {"s2"}       # KB_MODE=off


@pytest.mark.parametrize("counts,expected", [
    ({"a": 9, "b": 2, "none": 1}, ["a", "b"]),
    ({"a": 4, "b": 3, "c": 2, "d": 1}, ["a", "b", "c"]),               # max 3
    ({"a": 9, "none": 2}, ["a", "none"]),                             # a covers 82 %, none 18 % >= 10 %
    ({"a": 4, "b": 3, "c": 2, "none": 1}, ["a", "b", "none"]),        # none takes the last place
    ({"none": 8, "a": 2}, ["none"]),                                  # 80 % covered by none alone
])
def test_pick_reps(counts, expected):
    c = Counter(counts)
    order = sorted(c, key=lambda k: -c[k])
    assert pick_reps(order, c, sum(c.values()), 0.8, 0.10, 3) == expected
