"""Fake synthetic KB cases in the test KB DB (mock embedding vectors)."""

from __future__ import annotations

import json

from sqlalchemy import text

from spira_server.db.engine import make_engine
from spira_server.kb import embedding

from .conftest import TEST_KB_DB

_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = make_engine(TEST_KB_DB)
    return _engine


def clear() -> None:
    with engine().begin() as conn:
        conn.execute(text("TRUNCATE cases"))


def add(case_id: str, items: list[str], intent_id: str, *, intent_text: str = "", situation: dict | None = None,
        calendar_tags: list[str] | None = None, types: list[str] | None = None, kb_version: str = "kb-v1") -> None:
    vec = "[" + ",".join(f"{x:.7g}" for x in embedding.embed_basket(items)) + "]"
    with engine().begin() as conn:
        conn.execute(text(
            'INSERT INTO cases (case_id, source, items, intent_id, intent_text, situation, "when", household, '
            "basket_emb, kb_version) VALUES (:id, 'synthetic', :items, :intent, :text, CAST(:sit AS jsonb), "
            "CAST(:when AS jsonb), CAST(:house AS jsonb), CAST(:vec AS vector), :ver)"),
            {"id": case_id, "items": sorted(items), "intent": intent_id, "text": intent_text or None,
             "sit": json.dumps(situation or {"event": None, "guests": None, "activity": None, "theme": None},
                               ensure_ascii=False),
             "when": json.dumps({"calendar_tags": calendar_tags or []}, ensure_ascii=False),
             "house": json.dumps({"types": types or []}, ensure_ascii=False), "vec": vec, "ver": kb_version})


EP9031 = ["딸기", "컵케이크 믹스", "휘핑크림", "세탁 세제", "로션", "풍선", "케이크 토퍼", "고깔모자", "아이싱 펜"]


def seed_birthday_neighbours() -> None:
    """12 similar cases (9 kid birthday, 2 home baking, 1 none) + 3 dissimilar ones."""
    party = ["풍선", "케이크 토퍼", "고깔모자", "딸기", "아이싱 펜", "휘핑크림", "컵케이크 믹스"]
    for n in range(9):
        shared = [party[(n + k) % len(party)] for k in range(6)]
        add(f"syn_T1_{n:04d}", shared + ["생일 초"], "kid_birthday_party",
            intent_text="아이 친구들을 집에 초대해 생일 파티를 여는 준비",
            situation={"event": "생일", "guests": "아이 친구들", "activity": None, "theme": None},
            calendar_tags=["생일"] if n < 5 else [], types=["3~4인", "초등 자녀"])
    for n in range(2):
        add(f"syn_T2_{n:04d}", ["딸기", "컵케이크 믹스", "휘핑크림", "아이싱 펜", "케이크 토퍼", "풍선", "버터"],
            "home_baking", intent_text="주말에 컵케이크를 구워 보려는 홈베이킹",
            situation={"event": None, "guests": None, "activity": "컵케이크 굽기", "theme": None},
            types=["2인", "부부·커플"])
    add("syn_T3_0000", ["세탁 세제", "로션", "딸기", "휘핑크림", "컵케이크 믹스", "아이싱 펜", "우유"], "none",
        intent_text=None, types=["1인"])
    for n in range(3):
        add(f"syn_T9_{n:04d}", ["라면", "생수", "휴지", "샴푸", "딸기", f"잡화{n}"], "none")
