"""S1 post-processing in code (spec §7.4): T5 deals, T6 word list, core_noun, labels, attributes, in-pass dedupe."""

import pytest

from spira_server.config import get_config
from spira_server.pipeline.s1_extract import apply_deal, core_noun, label_for, postprocess, sensitive_hit


@pytest.mark.parametrize("qty,deal,expected", [
    (1, "1+1", 2), (1, "2+1", 3), (2, "2+1", 6), (3, None, 3), (None, "1+1", 2), (None, None, None),
    (2, "쿠폰할인", 2), (500, "1+1", 999),
])
def test_t5_deals(qty, deal, expected):
    assert apply_deal(qty, deal) == expected


@pytest.mark.parametrize("name,hit", [
    ("OO 치약 120g", False), ("종합 감기약", True), ("약산성 클렌저", False), ("임신테스트기", True),
    ("비타민 C 1000", False), ("콘돔 12개입", True), ("약콩 두유", False),
])
def test_t6_sensitive_words(name, hit):
    assert sensitive_hit(name, get_config()) is hit


@pytest.mark.parametrize("name,noun", [
    ("OO 유기농 설향 딸기 500g", "딸기"), ("동물성 휘핑크림 500ml (냉장)", "휘핑크림"), ("CJ 햇반 210g 12개입", "햇반"),
    ("국산 [특가] 바지락", "바지락"),
])
def test_core_noun(name, noun):
    assert core_noun(name) == noun


def test_labels():
    cfg = get_config()
    assert label_for("농축수산물", "딸기", [], cfg) == "care"
    assert label_for("가구", "책상", [], cfg) == "clue"
    assert label_for("가구", "슈퍼싱글 매트리스", [], cfg) == "care"
    assert label_for("화장품", "로션", [], cfg) == "clue"
    assert label_for("화장품", "앰플", [{"key": "보관", "value": "냉장"}], cfg) == "care"
    assert label_for(None, "무언가", [], cfg) == "clue"


def _rows(*lines):
    rows = [{"name": n, "type": "우유", "group": "음·식료품", "qty": q, "order_no": o} for n, q, o in lines]
    return postprocess(rows, get_config())


def test_same_item_rule():
    assert len(_rows(("서울우유 1L", 2, None), ("서울우유 1L", 2, None))) == 1            # overlapping screenshots
    assert [r["qty"] for r in _rows(("서울우유 1L", 1, None), ("서울우유 1L", 2, None))] == [1, 2]   # bought twice
    assert [r["qty"] for r in _rows(("서울우유 1L", None, None), ("서울우유 1L", 2, None))] == [2]   # qty cropped
    assert len(_rows(("서울우유 1L", 2, "A"), ("서울우유 1L", 2, "B"))) == 2              # two orders
    assert len(_rows(("서울우유 1L", 2, "A"), ("서울우유 1L", 2, None))) == 1
    assert len(_rows(("서울우유 1L", 1, None), ("매일우유 900ml", 1, None))) == 2


def test_postprocess_rules():
    rows = postprocess([
        {"name": "", "type": "빈 이름", "group": None},
        {"name": "OO 유기농 딸기 500g", "type": "", "group": "농축수산물", "qty": None,
         "attributes": [{"key": "보관", "value": "냉장", "source": "냉장"},
                        {"key": "가공", "value": "세척", "source": "유기농"}]},
        {"name": "OO 유기농 딸기 500g", "type": "딸기", "group": "농축수산물", "qty": 2},
        {"name": "OO 유기농 딸기 500g", "type": "딸기", "group": "농축수산물", "qty": 2, "order_no": "B"},
    ], get_config())
    assert len(rows) == 1
    [r] = rows
    assert r["type"] == "딸기"
    assert r["attributes"] == [{"key": "가공", "value": "세척", "source": "유기농"}]   # source must be in the name
    assert r["qty"] == 2 and r["order_no"] == "B"                                     # gaps filled from duplicates
