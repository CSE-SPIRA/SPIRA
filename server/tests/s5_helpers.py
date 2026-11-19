"""Scenario builders for S5 tests: ep_9031, ep_9120 (held, speaker) and ep_9150 (groceries) up to S4."""

from __future__ import annotations

import copy

from sqlalchemy import text

from spira_server import clock
from spira_server.db.engine import server_engine
from spira_server.pipeline import s4_tasks

from .factories import fixture, household
from .s4_helpers import devices, episode, output, record

F = "생활용품 – 휴지·위생, 파티용품"


def restart_card_ids(n: int) -> None:
    with server_engine().begin() as conn:
        conn.execute(text(f"ALTER SEQUENCE card_id_seq RESTART WITH {n}"))


def s4_for(mock_llm, episode_id: str, out: dict, now):
    record(mock_llm, episode_id, out, now=now)
    return s4_tasks.generate(episode_id, now=now)


# ep_9120: family gathering, no calendar yet -> held lines; one fridge notice
SHARED_9120 = clock.parse("2026-11-02T20:00:05+09:00")
JUDGED_9120 = clock.parse("2026-11-02T20:11:30+09:00")
ITEMS_9120 = [
    {"name": "한우 불고기용 600g", "type": "소고기", "group": "농축수산물", "qty": 2},
    {"name": "잡채용 당면 500g", "type": "당면", "group": "음·식료품", "qty": 1},
    {"name": "일회용 앞접시 20개입", "type": "앞접시", "group": F, "qty": 1,
     "attributes": [{"key": "포장", "value": "20개입", "source": "20개입"}]},
]
INTENT_9120 = {"bundles": [{
    "intent_id": "family_gathering", "intent_text": "부모님을 집에 모셔 불고기와 잡채로 식사를 대접하려는 준비",
    "items": ["소고기", "당면", "앞접시"],
    "situation": {"event": None, "guests": "부모님", "activity": "불고기·잡채 식사", "theme": None},
    "basis": {"intent": ["소고기", "당면", "앞접시"], "event": [], "guests": ["앞접시"], "activity": ["소고기", "당면"],
              "theme": []},
    "calendar_event_id": None, "calendar_tags": [], "use_window": None}],
    "unbundled": [], "none_reason": None, "error": None}
OUT_9120 = {
    "needs": [{"id": "n1", "bundle": 1, "need": "손님 오기 전 거실 정리", "from": ["guests"]},
              {"id": "n2", "bundle": 1, "need": "가족이 오면 편안한 분위기", "from": ["guests"]}],
    "tasks": [
        {"need_id": "n1", "slug": "clean", "way": "run", "target_room": "거실",
         "actions": [{"key": "cleaner_01.clean", "value": {"room": "거실"}}],
         "trigger": {"kind": "before_start", "minutes": 90}, "line": "손님 오기 전 거실 청소"},
        {"need_id": "n2", "slug": "music", "way": "run", "target_room": "거실",
         "actions": [{"key": "speaker_01.play", "value": {"playlist": "family", "volume": 25}}],
         "trigger": {"kind": "guest_arrived"}, "line": "가족이 오시면 잔잔한 음악"}],
    "fridge_notices": [
        {"item": "소고기", "kind": "storage", "point": "핏물이 고이면 상한다", "intent_change": None,
         "text": "핏물을 키친타월로 닦고 양념하기 전까지 냉장고 맨 아래 칸에 두세요"},
        {"item": "당면", "kind": None, "point": None, "intent_change": None, "text": None}]}


def ep9120() -> str:
    household("h_051", types=["2인", "부부·커플"])
    devices("h_051", fixture("ep_9120/devices.json"))
    return episode("ep_9120", intent=copy.deepcopy(INTENT_9120), raw_items=ITEMS_9120, hid="h_051",
                   shared=SHARED_9120)


# ep_9150: groceries, no intent -> two notices only
SHARED_9150 = clock.parse("2026-11-04T19:30:41+09:00")
JUDGED_9150 = clock.parse("2026-11-04T19:41:05+09:00")
ITEMS_9150 = [
    {"name": "서울우유 1L", "type": "우유", "group": "음·식료품", "qty": 2},
    {"name": "무항생제 계란 15구", "type": "계란", "group": "농축수산물", "qty": 1},
    {"name": "통영 바지락 500g", "type": "바지락", "group": "농축수산물", "qty": 1},
    {"name": "3겹 롤휴지 30롤", "type": "휴지", "group": F, "qty": 1},
    {"name": "OO 주방세제 1L", "type": "주방 세제", "group": "생활용품 – 세제·청소용품", "qty": 1},
    {"name": "설향 딸기 500g", "type": "딸기", "group": "농축수산물", "qty": 1},
]
OUT_9150 = {"needs": [], "tasks": [], "fridge_notices": [
    {"item": "우유", "kind": None, "point": None, "intent_change": None, "text": None},
    {"item": "계란", "kind": None, "point": None, "intent_change": None, "text": None},
    {"item": "바지락", "kind": "prep", "point": "사 온 그대로 끓이면 모래가 씹힌다", "intent_change": None,
     "text": "소금물(물 1L에 소금 2큰술)에 담고 검은 봉지를 덮어 냉장고에서 2~3시간 해감한 뒤 드세요"},
    {"item": "딸기", "kind": "storage", "point": "빨리 무른다", "intent_change": None,
     "text": "사흘 안에 못 드시면 꼭지를 떼고 씻어 물기를 닦은 뒤 냉동해 두세요"}]}


def ep9150() -> str:
    household()
    devices()
    return episode("ep_9150", intent={"bundles": [], "unbundled": [i["type"] for i in ITEMS_9150],
                                      "none_reason": "평소 장보기", "error": None},
                   raw_items=ITEMS_9150, shared=SHARED_9150)


__all__ = ["output"]
