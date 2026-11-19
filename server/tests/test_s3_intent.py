"""S3 intent judgement (spec §9): T13 T14 T15, ep_9031 decision, bundles limit, unclassified, empty blocks."""

import copy
from pathlib import Path

from sqlalchemy import select

from spira_server.db.engine import session_scope
from spira_server.db.models import Episode, LlmCall
from spira_server.llm import prompts
from spira_server.llm.client import retry_text
from spira_server.pipeline import s2_context, s3_intent
from spira_server.pipeline.s3_intent import build_intent_message, judge_from_context

from .factories import data, fixture
from .s2_helpers import ep9031

EXPECTED = Path(__file__).parent / "expected" / "s3_message_ep_9031.txt"
D = data("s3_ep_9031.json")


def _ctx(**drop):
    ctx = copy.deepcopy(D["context"])
    for key in drop:
        ctx["for_intent"].pop(key, None)
    return ctx


def _record(mock_llm, ctx, items, output, retry_errors=None, retry_output=None):
    user = build_intent_message(ctx, items)
    mock_llm.record("s3", prompts.system("s3"), user, output=output)
    if retry_errors is not None:
        user2 = user + "\n\n" + retry_text(prompts.text("s3_retry.txt"), retry_errors)
        mock_llm.record("s3", prompts.system("s3"), user2, output=retry_output)


def test_t13_message_ep9031():
    assert build_intent_message(D["context"], D["items"]) == EXPECTED.read_text(encoding="utf-8")


def test_t13_c0_and_c1():
    c0 = build_intent_message(_ctx(this_home=1, kb_neighbors=1), D["items"])
    assert "다른 집" not in c0 and "이 집" not in c0
    assert c0.startswith("[이번 주문]") and "[주문 시각]\n10월 15일 (목) 21:00에 공유됨" in c0
    c1 = build_intent_message(_ctx(this_home=1), D["items"])
    assert "[비슷한 다른 집 주문]" in c1 and "[이 집" not in c1 and "[캘린더 일정]" not in c1


def test_empty_blocks_use_status_lines():
    ctx = _ctx()
    home = ctx["for_intent"]["this_home"]
    home.update(household_types=[], unusual_items={"status": "insufficient"}, calendar=[])
    ctx["for_intent"]["kb_neighbors"] = {"similar_count": 3, "note": "비슷한 사례가 거의 없음"}
    msg = build_intent_message(ctx, D["items"])
    assert "[이 집 가구 유형]" not in msg
    assert "[이 집 지난 90일 주문과 비교]\n이 집 주문 기록이 10개 미만이라 비교하지 않음" in msg
    assert "[캘린더 일정]\n14일 안에 행사 태그가 붙은 일정 없음" in msg
    assert "다른 집 주문이 거의 없다 (3건)" in msg
    home["unusual_items"] = {"status": "all_usual"}
    assert "이번 물건은 모두 이 집이 평소 사는 물건이다." in build_intent_message(ctx, D["items"])


def test_ep9031_decision_matches_rationale(mock_llm):
    _record(mock_llm, D["context"], D["items"], D["decision"])
    intent = judge_from_context(D["context"], D["items"])
    want = fixture("ep_9031/rationale.json")["intents"][0]
    [b] = intent["bundles"]
    for key in ("intent_id", "intent_text", "situation", "basis", "calendar_event_id", "calendar_tags"):
        assert b[key] == want[key], key
    assert b["use_window"] == {"start": "2026-10-17T14:00:00+09:00", "end": "2026-10-17T17:00:00+09:00"}
    assert intent["unbundled"] == ["세탁 세제", "로션"] == fixture("ep_9031/rationale.json")["unbundled"]
    assert intent["none_reason"] is None and intent["error"] is None


def _bundle(**kw):
    b = copy.deepcopy(D["decision"]["bundles"][0])
    b.update(kw)
    return b


def test_t14_item_in_two_bundles_then_no_intent(mock_llm, session):
    two = {"bundles": [_bundle(), _bundle(intent_id="home_baking", intent_text="컵케이크를 굽고 꾸미려는 준비",
                                          items=["딸기", "휘핑크림"],
                                          situation={"event": None, "guests": None, "activity": None, "theme": None},
                                          calendar_event_id=None)], "none_reason": None}
    errors = ['물건 "딸기": 묶음 1과 묶음 2에 함께 있다. 물건 하나는 한 묶음에만 넣는다',
              '물건 "휘핑크림": 묶음 1과 묶음 2에 함께 있다. 물건 하나는 한 묶음에만 넣는다']
    _record(mock_llm, D["context"], D["items"], two, retry_errors=errors, retry_output=two)
    intent = judge_from_context(D["context"], D["items"])
    assert (intent["bundles"], intent["none_reason"]) == ([], "format_fail")
    assert intent["unbundled"] == [i["type"] for i in D["items"]]
    assert mock_llm.calls("s3") == 2
    assert session.execute(select(LlmCall.outcome)).scalar_one() == "format_fail"


def test_t14_field_missing_from_text_retried(mock_llm):
    bad = {"bundles": [_bundle(intent_text="손님 여럿이 오는 아이 생일 파티를 열고 컵케이크를 굽고 꾸미려는 준비")],
           "none_reason": None}
    errors = ['묶음 1의 theme "디즈니 공주": intent_text에 없다. 채운 상황 칸을 intent_text에 모두 담는다']
    _record(mock_llm, D["context"], D["items"], bad, retry_errors=errors, retry_output=D["decision"])
    intent = judge_from_context(D["context"], D["items"])
    assert intent["bundles"][0]["situation"]["theme"] == "디즈니 공주"
    assert mock_llm.calls("s3") == 2


def test_t15_field_without_basis_is_nulled(mock_llm):
    b = _bundle()
    b["basis"]["guests"] = []
    _record(mock_llm, D["context"], D["items"], {"bundles": [b], "none_reason": None})
    intent = judge_from_context(D["context"], D["items"])
    assert intent["bundles"][0]["situation"]["guests"] is None
    assert intent["error"] == {"notes": ["bundle 1: guests without basis -> null"]}
    assert mock_llm.calls("s3") == 1


def test_no_intent_groceries(mock_llm):
    items = [{"item_id": "it_1", "type": "우유", "qty": 2, "attributes": []},
             {"item_id": "it_2", "type": "바지락", "qty": 1, "attributes": []}]
    ctx = _ctx(kb_neighbors=1)
    ctx["for_intent"]["this_home"]["calendar"] = []
    _record(mock_llm, ctx, items, {"bundles": [], "none_reason": "평소 장보기로 보인다"})
    intent = judge_from_context(ctx, items)
    assert intent == {"bundles": [], "unbundled": ["우유", "바지락"], "none_reason": "평소 장보기로 보인다",
                      "error": None}


def test_three_bundles_keep_two_largest_and_unclassified(mock_llm):
    sit = {"event": None, "guests": None, "activity": None, "theme": None}
    basis = {"intent": ["로션"], "event": [], "guests": [], "activity": [], "theme": []}
    out = {"bundles": [
        _bundle(items=["케이크 토퍼", "고깔모자", "풍선"]),
        {"intent_id": "unclassified", "intent_text": "아기 피부 관리", "items": ["로션"], "situation": sit,
         "basis": basis, "calendar_event_id": None},
        {"intent_id": "home_baking", "intent_text": "홈베이킹",
         "items": ["컵케이크 믹스", "휘핑크림", "딸기", "아이싱 펜"],
         "situation": sit, "basis": {**basis, "intent": ["컵케이크 믹스"]}, "calendar_event_id": None}],
        "none_reason": None}
    _record(mock_llm, D["context"], D["items"], out)
    intent = judge_from_context(D["context"], D["items"])
    assert [b["intent_id"] for b in intent["bundles"]] == ["kid_birthday_party", "home_baking"]
    assert intent["unbundled"] == ["세탁 세제", "로션"]


def test_schema_rejects_unknown_labels_items_and_calendar_ids():
    import pytest
    from pydantic import ValidationError

    from spira_server.kb.lists import get_lists
    from spira_server.pipeline.s3_intent import build_schema

    schema = build_schema([i["type"] for i in D["items"]], ["c1", "c2"], get_lists().intent_ids)
    schema.model_validate(D["decision"])
    for bad in (_bundle(intent_id="birthday"), _bundle(items=["케이크"]), _bundle(calendar_event_id="c9"),
                _bundle(basis={**D["decision"]["bundles"][0]["basis"], "intent": []})):
        with pytest.raises(ValidationError):
            schema.model_validate({"bundles": [bad], "none_reason": None})
    no_cal = build_schema(["딸기"], [], get_lists().intent_ids)
    with pytest.raises(ValidationError):
        no_cal.model_validate({"bundles": [_bundle(items=["딸기"], basis={"intent": ["딸기"]})], "none_reason": None})


def test_run_stores_intent(mock_llm):
    ep = ep9031()
    s2_context.run(ep)
    with session_scope() as s:
        ctx = s.get(Episode, ep).context
    with session_scope() as s:
        items = s3_intent.item_dicts(s2_context.item_types(s, ep))
    _record(mock_llm, ctx, items, D["decision"])
    s3_intent.run(ep)
    with session_scope() as s:
        e = s.get(Episode, ep)
        assert e.intent["bundles"][0]["intent_id"] == "kid_birthday_party"
        assert e.stage == "s2"
