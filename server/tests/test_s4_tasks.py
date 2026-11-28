"""S4 task generation (spec §10): T17 T18 T19 T20 T21 T42 T66, per-item rules, held tasks, message."""

import copy

import pytest

from spira_server import clock
from spira_server.db.engine import session_scope
from spira_server.db.models import Case, Household
from spira_server.kb import embedding
from spira_server.pipeline import s4_tasks

from .factories import fixture, household
from .s4_helpers import JUDGED, devices, ep9031, episode, intent_ep9031, output, plan_v1_tasks, record


def _gen(ep="ep_9031", now=JUDGED):
    return s4_tasks.generate(ep, now=now)


def test_t17_ep9031_drafts_equal_plan_v1(mock_llm):
    ep = ep9031()
    message = record(mock_llm, ep, output())
    r = _gen(ep)
    assert [d.contract() for d in r.drafts] == plan_v1_tasks()
    assert r.next_task_n == 7 and mock_llm.calls("s4") == 1
    clean = r.drafts[0]
    assert (clean.need, clean.line, clean.target_room, clean.bundle) == (
        "손님 오기 전 거실 정리", "손님 오기 전 거실 청소", "거실", 0)
    fridge = r.drafts[4]
    assert fridge.meta["kind"] == "storage" and fridge.meta["item"] == "딸기"
    assert "시각: 토요일 14:00~17:00 (2일 뒤)" in message
    assert ("- light_01 · 조명 · 거실 · color(hue 0~360, brightness 0~100, saturation 0~100), "   # jsonb key order
            "color_temp(kelvin 2700~6500)") in message
    assert "- 딸기 × 2 [보관: 냉장] · 농축수산물 · 의도 1의 물건" in message   # R47 attributes
    assert "- 컵케이크 믹스 × 모름 · 음·식료품 · 의도 1의 물건" in message
    assert "- fridge_01 · 냉장고 · 주방 · show_notice(글자)" in message
    assert "- cooktop_01 · 인덕션 · 주방 · child_lock" in message      # heat is in never: left out


def test_t42_demo_before_start_and_windows(mock_llm, env):
    env(DEMO_MODE="1")
    ep = ep9031()
    record(mock_llm, ep, output())
    tasks = {d.task_id: d for d in _gen(ep).drafts}
    assert tasks["t_clean#1"].trigger == {"time": "2026-10-17T13:57:00+09:00"}       # 3 min, though S4 wrote 90
    assert tasks["t_safe#2"].trigger == {"time": "2026-10-17T13:57:00+09:00"}
    assert tasks["t_mood#3"].trigger["window"]["from"] == "2026-10-17T13:59:00+09:00"
    assert tasks["t_clean#1"].end["or_time"] == "2026-10-17T17:10:00+09:00"
    assert tasks["t_fridge#5"].end == {"on": "fridge.door_opened", "after": "2m", "or_after": "12h",
                                       "restore": False}


def _memory_row(verdict="match", feedback=None, created=None):
    row = fixture("ep_9031/case_row.json")
    with session_scope() as s:
        s.add(Case(case_id=row["case_id"] if verdict == "match" else f"home_h_042_ep_8_{len(verdict)}",
                   source="this_home", items=row["items"], intent_id=row["intent_id"], intent_text=row["intent_text"],
                   situation=row["situation"], when=row["when"], household=row["household"],
                   basket_emb=embedding.embed_basket(row["items"]), household_id="h_042", home_did=row["home_did"],
                   verdict=verdict, task_feedback=feedback if feedback is not None else row["task_feedback"],
                   created_at=created or clock.parse("2026-10-17T18:00:00+09:00")))


def test_t18_second_birthday_uses_memory(mock_llm):
    household()
    devices()
    _memory_row()
    episode("ep_9500", shared=clock.parse("2026-11-12T20:00:00+09:00"),
            intent={**intent_ep9031(), "bundles": [{**intent_ep9031()["bundles"][0], "use_window": {
                "start": "2026-11-14T14:00:00+09:00", "end": "2026-11-14T17:00:00+09:00"}}]})
    out = output()
    out["tasks"][2]["actions"][1] = {"key": "light_01.color_temp", "value": {"kelvin": 2700}}
    now = clock.parse("2026-11-12T20:11:00+09:00")
    message = record(mock_llm, "ep_9500", out, now=now)
    assert "[이 집이 지난번 같은 의도에서 남긴 반응]" in message
    assert "손님 오기 전 거실 청소 (cleaner.clean)" in message
    assert "일정 시작 70분 뒤 조명을 color_temp(kelvin 2700)로 바꿈" in message
    r = _gen("ep_9500", now=now)
    slugs = [d.task_id for d in r.drafts]
    assert slugs == ["t_safe#1", "t_mood#2", "t_oven#3", "t_fridge#4", "t_fridge#5"]   # cleaning switched off
    assert {"slug": "clean", "reason": "switched_off"} in r.dropped
    assert r.dropped_detail["clean"]["line"] == "손님 오기 전 거실 청소" and r.dropped_detail["clean"]["actions"] == ["cleaner_01.clean"]
    mood = r.drafts[1]
    assert {"device": "light_01", "cmd": "color_temp", "value": {"kelvin": 2700}} in mood.actions


def test_t19_stopped_before_then_later_match(mock_llm):
    household()
    devices()
    _memory_row(verdict="stopped", feedback=[], created=clock.parse("2026-10-01T10:00:00+09:00"))
    ep = episode()
    record(mock_llm, ep, output())
    r = _gen(ep)
    assert r.skipped_bundles == {0: "stopped_before"}
    assert all(d.source == "item" for d in r.drafts) and [d.task_id for d in r.drafts] == ["t_fridge#1", "t_fridge#2"]
    _memory_row(verdict="match", created=clock.parse("2026-10-10T10:00:00+09:00"))     # a later match lifts it
    record(mock_llm, ep, output())
    r2 = _gen(ep)
    assert not r2.skipped_bundles and any(d.source == "situation" for d in r2.drafts)


def test_t20_unclassified_no_run_tasks(mock_llm):
    ep9031_intent = intent_ep9031()
    ep9031_intent["bundles"][0]["intent_id"] = "unclassified"
    household()
    devices()
    ep = episode(intent=ep9031_intent)
    record(mock_llm, ep, output())
    r = _gen(ep)
    assert [d.task_id for d in r.drafts if d.source == "situation"] == ["t_oven#1"]
    assert {x["reason"] for x in r.dropped} == {"unclassified_run"}


def test_t21_value_out_of_range_after_retry_drops_that_task(mock_llm):
    ep = ep9031()
    out = output()
    out["tasks"][2]["actions"][1]["value"]["hue"] = 400
    p = s4_tasks.prepare(ep, now=JUDGED)
    from pydantic import ValidationError
    try:
        p.schema.model_validate(out)
    except ValidationError as e:
        from spira_server.llm.client import pydantic_errors
        errors = pydantic_errors(e)
    record(mock_llm, ep, out, retry_errors=errors, retry_output=out)
    r = _gen(ep)
    assert [d.task_id for d in r.drafts] == ["t_clean#1", "t_safe#2", "t_oven#3", "t_fridge#4", "t_fridge#5"]
    assert {"slug": "mood", "reason": "schema"} in r.dropped
    assert r.dropped_detail["mood"]["line"]                     # what the dropped task said, for display


def test_format_rules_after_retry(mock_llm):
    ep = ep9031()
    out = output()
    out["tasks"][3]["trigger"] = {"kind": "before_start", "minutes": 10}      # standby with a trigger
    errors = ["할 일 4: standby에는 trigger를 쓰지 않는다"]
    record(mock_llm, ep, out, retry_errors=errors, retry_output=out)
    r = _gen(ep)
    assert "t_oven" not in " ".join(d.task_id for d in r.drafts)
    assert {"slug": "oven", "reason": "format"} in r.dropped
    assert r.dropped_detail["oven"]["way"] == "standby" and r.dropped_detail["oven"]["need"]


def test_t66_shared_screen_notice_rule(mock_llm):
    ep = ep9031()
    out = output()
    out["fridge_notices"][0]["text"] = "토요일 생일 파티 전에 씻어 주세요"
    out["fridge_notices"][2]["text"] = "디즈니 공주 케이크 꾸미기 직전까지 차갑게 두세요"
    record(mock_llm, ep, out)
    r = _gen(ep)
    assert [d.task_id for d in r.drafts] == ["t_clean#1", "t_safe#2", "t_mood#3", "t_oven#4"]
    assert {x["word"] for x in r.dropped if x["reason"] == "public_text"} == {"생일", "디즈니 공주"}
    out["fridge_notices"][0]["text"] = "토요일 꾸미기 직전에 씻어 주세요"        # a weekday alone is fine
    out["fridge_notices"][2]["text"] = None
    record(mock_llm, ep, out)
    assert [d.task_id for d in _gen(ep).drafts][-1] == "t_fridge#5"


def test_held_when_no_time(mock_llm):
    intent = intent_ep9031()
    intent["bundles"][0]["use_window"] = None
    intent["bundles"][0]["calendar_event_id"] = None
    household()
    devices()
    ep = episode(intent=intent)
    message = record(mock_llm, ep, output())
    assert "시각: 모름 (일정이 아직 없음)" in message
    tasks = {d.task_id: d for d in _gen(ep).drafts}
    assert tasks["t_clean#1"].held and tasks["t_safe#2"].held and tasks["t_mood#3"].held
    assert tasks["t_oven#4"].trigger == {"event": "package.brought_in", "released": False}
    assert tasks["t_oven#4"].end == {"on": "oven.started", "by": "user", "or_after": "24h", "restore": False}


def test_paused_or_no_devices(mock_llm):
    ep9031(with_devices=False)
    r = _gen()
    assert r.drafts == [] and mock_llm.calls() == 0
    devices()
    with session_scope() as s:
        s.get(Household, "h_042").paused = True
    assert _gen().drafts == [] and mock_llm.calls() == 0


def _plain_order(items: list[dict], body_extra: list[dict]):
    household()
    body = copy.deepcopy(fixture("ep_9031/devices.json"))
    body["devices"] += body_extra
    devices(body=body)
    return episode("ep_7", intent={"bundles": [], "unbundled": [], "none_reason": "장보기", "error": None},
                   raw_items=items)


PURIFIER = {"id": "purifier_01", "type": "purifier", "room": "침실", "substrate": "virtual",
            "commands": [{"cmd": "mode", "value_schema": {"mode": {"enum": ["auto", "deodorize"], "default": "auto"}}}],
            "events": ["changed"], "never": [], "noisy": False}
STYLER = {"id": "styler_01", "type": "styler", "room": "드레스룸", "substrate": "virtual",
          "commands": [{"cmd": "set_course_standby",
                        "value_schema": {"course": {"enum": ["표준", "울케어"], "default": "표준"}}}],
          "events": ["started"], "never": [], "noisy": True}


def test_item_tasks_without_llm():
    _plain_order([
        {"name": "슈퍼싱글 매트리스", "type": "매트리스", "group": "가구", "qty": 1},
        {"name": "울 니트 가디건", "type": "가디건", "group": "의복", "qty": 1,
         "attributes": [{"key": "재질", "value": "울", "source": "울"}]},
        {"name": "세탁 세제", "type": "세탁 세제", "group": "생활용품 – 세제·청소용품", "qty": 1},
    ], [PURIFIER, STYLER])
    r = _gen("ep_7")
    assert [d.contract() for d in r.drafts] == [
        {"task_id": "t_styler#1", "source": "item", "way": "standby",
         "actions": [{"device": "styler_01", "cmd": "set_course_standby", "value": {"course": "울케어"}}],
         "trigger": {"event": "package.brought_in", "released": False},
         "end": {"on": "styler.started", "by": "user", "restore": False}},
        {"task_id": "t_mattress#2", "source": "item", "way": "run",
         "actions": [{"device": "purifier_01", "cmd": "mode", "value": {"mode": "deodorize"}}],
         "trigger": {"event": "package.brought_in", "released": False},
         "end": {"on": "purifier.odor_normal", "or_after": "72h", "restore": True}},
    ]
    assert not r.llm_called


def test_bulk_freeze_and_ambiguous_targets(mock_llm):
    fridge2 = {**copy.deepcopy(fixture("ep_9031/devices.json")["devices"][5]), "id": "fridge_02"}
    _plain_order([{"name": "냉동 닭가슴살 2kg", "type": "닭가슴살", "group": "음·식료품", "qty": 1}], [fridge2])
    r = _gen("ep_7")
    assert r.drafts == [] and not r.llm_called            # two fridges: notice and freeze skipped (R8)


@pytest.mark.parametrize("qty,name,bulk", [
    (3, "닭가슴살", True), (1, "닭가슴살 1kg", True), (2, "닭가슴살 500g", False)])
def test_bulk_rule(qty, name, bulk):
    from spira_server.config import get_config
    from spira_server.db.models import OrderItem
    item = OrderItem(type="닭가슴살", name=name, grp="음·식료품", qty=qty, attributes=[], label="care", masked=False)
    spec = next(t for t in get_config().item_tasks["tasks"] if t["name"] == "freeze")
    assert s4_tasks.rule_matches(spec["when"], item, get_config().item_tasks["bulk"]) is bulk


def test_r58_after_start_before_end_and_restore_inside_the_schedule(mock_llm):
    """R58: the LLM picks when to act and when to put things back between the calendar start and end."""
    ep = ep9031()                                            # 토요일 14:00~17:00 (180 minutes)
    out = output()
    out["tasks"][0]["trigger"] = {"kind": "after_start", "minutes": 60}                 # clean once everyone is out
    out["tasks"][1]["trigger"] = {"kind": "after_start", "minutes": 30}                 # lock, put back before the end
    out["tasks"][1]["end_before_end_minutes"] = 30
    record(mock_llm, ep, out)
    tasks = {d.task_id: d for d in _gen(ep).drafts}
    assert tasks["t_clean#1"].trigger == {"time": "2026-10-17T15:00:00+09:00"}
    assert tasks["t_safe#2"].trigger == {"time": "2026-10-17T14:30:00+09:00"}
    assert tasks["t_safe#2"].end == {"time": "2026-10-17T16:30:00+09:00", "restore": True}


@pytest.mark.parametrize("trigger,extra,word", [
    ({"kind": "after_start", "minutes": 200}, {}, "일정 길이"),                      # past the end
    ({"kind": "before_end", "minutes": None}, {}, "minutes"),
    ({"kind": "after_start", "minutes": 60}, {"end_after_start_minutes": 30}, "실행 시점보다 뒤"),
    ({"kind": "after_start", "minutes": 10}, {"end_before_end_minutes": 0, "end_after_start_minutes": 20}, "하나만"),
])
def test_r58_times_outside_the_schedule_are_format_errors(trigger, extra, word):
    ep = ep9031()
    out = output()
    out["tasks"][1]["trigger"] = trigger
    out["tasks"][1].update(extra)
    p = s4_tasks.prepare(ep, now=JUDGED)
    errs = s4_tasks.task_errors(p.schema.model_validate(out), p.bundles)
    assert any(i == 1 and word in msg for i, msg in errs), errs
