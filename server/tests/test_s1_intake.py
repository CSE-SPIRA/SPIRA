"""S1 receive and read (spec §7): T2 T3 T4 T6 T7 T40 T44 T55 T61, plus request checks and order-number merge."""

from datetime import timedelta

import pytest
from spira_contracts.validate import validate
from sqlalchemy import select

from spira_server import clock, scheduler
from spira_server.db.engine import session_scope
from spira_server.db.models import Episode, EpisodeImage, LlmCall, Order, OrderItem
from spira_server.pipeline import s1_extract

from .factories import data, household, png
from .s1_helpers import THU_2100, client, post, record_s1, run_quiet


@pytest.fixture(autouse=True)
def downstream(monkeypatch):
    """S1 tests stop at S1: record which episodes would go on to S2-S5."""
    called: list[str] = []
    monkeypatch.setattr(s1_extract.runner, "after_s1", called.append)
    return called


def _items(episode_id: str) -> list[OrderItem]:
    with session_scope() as s:
        return s.execute(select(OrderItem).where(OrderItem.episode_id == episode_id)
                         .order_by(OrderItem.created_at, OrderItem.id)).scalars().all()


def _episode(episode_id: str) -> Episode:
    with session_scope() as s:
        return s.get(Episode, episode_id)


def _two_captures(mock_llm, app_headers):
    household()
    c = client()
    a, b = png(1), png(2)
    record_s1(mock_llm, [a, b], **{"output": data("s1_ep_9031.json")["output"]})
    clock.set_now(THU_2100)
    r1 = post(c, app_headers, [a], source_id="share-1")
    clock.set_now(THU_2100 + timedelta(seconds=64))
    r2 = post(c, app_headers, [b], source_id="share-2")
    return r1, r2


def test_t2_two_captures_one_episode_one_call(mock_llm, app_headers):
    r1, r2 = _two_captures(mock_llm, app_headers)
    assert r1.status_code == r2.status_code == 202
    ep = r1.json()["episode_id"]
    assert r2.json() == {"episode_id": ep, "status": "received"}
    for r in (r1, r2):
        validate(r.json(), "order_accepted.json")                                   # T40
    assert scheduler.pending[f"quiet:{ep}"] == THU_2100 + timedelta(seconds=64 + 600)

    run_quiet(ep, THU_2100 + timedelta(seconds=64 + 599))                          # one second early: nothing
    assert mock_llm.calls("s1") == 0
    run_quiet(ep, THU_2100 + timedelta(seconds=64 + 600))
    assert mock_llm.calls("s1") == 1
    run_quiet(ep, THU_2100 + timedelta(seconds=64 + 900))                          # running twice is safe
    assert mock_llm.calls("s1") == 1


def test_t4_ep9031_items(mock_llm, app_headers, downstream):
    r1, _ = _two_captures(mock_llm, app_headers)
    ep = r1.json()["episode_id"]
    run_quiet(ep, THU_2100 + timedelta(minutes=12))
    items = _items(ep)
    assert [i.id for i in items] == [f"it_{n}" for n in range(1, 10)]
    by_type = {i.type: i for i in items}
    assert len(items) == 9
    assert by_type["딸기"].label == by_type["휘핑크림"].label == "care"
    assert by_type["로션"].label == "clue"
    assert by_type["고깔모자"].qty == 6
    assert by_type["컵케이크 믹스"].qty is None
    assert by_type["케이크 토퍼"].attributes == [{"key": "테마", "value": "디즈니 공주", "source": "디즈니 공주"}]
    e = _episode(ep)
    assert (e.stage, e.status) == ("s1", "reading")
    assert downstream == [ep]                                 # handed on to S2-S5 once
    with session_scope() as s:
        assert s.execute(select(EpisodeImage).where(EpisodeImage.read.is_(False))).first() is None
        paths = [i.path for i in s.execute(select(EpisodeImage)).scalars()]
        assert sorted(o.order_no for o in s.execute(select(Order)).scalars()) == ["2026101500001", "2026101500002"]
        [call] = s.execute(select(LlmCall)).scalars().all()
        assert (call.stage, call.outcome, call.episode_id) == ("s1", "ok", ep)
    import os
    assert not any(os.path.exists(p) for p in paths)         # files deleted after the items were stored


def test_t3_same_source_id(mock_llm, app_headers):
    household()
    c = client()
    clock.set_now(THU_2100)
    r1 = post(c, app_headers, [png(1)], source_id="share-1")
    r2 = post(c, app_headers, [png(9)], source_id="share-1")
    assert (r1.status_code, r2.status_code) == (202, 200)
    assert r1.json()["episode_id"] == r2.json()["episode_id"]
    validate(r2.json(), "order_accepted.json")
    with session_scope() as s:
        assert len(s.execute(select(EpisodeImage)).scalars().all()) == 1
    assert mock_llm.calls() == 0


def test_t61_paused_same_source_id(mock_llm, app_headers):
    household(paused=True)
    c = client()
    r1 = post(c, app_headers, [png(1)], source_id="share-1")
    r2 = post(c, app_headers, [png(1)], source_id="share-1")
    assert (r1.status_code, r2.status_code) == (202, 200)
    assert r1.json() == r2.json() == {"episode_id": r1.json()["episode_id"], "status": "paused_skip"}
    with session_scope() as s:
        assert s.execute(select(EpisodeImage)).first() is None     # nothing will read them
    assert not scheduler.pending


def test_after_8_hours_new_episode(mock_llm, app_headers):
    household()
    c = client()
    clock.set_now(THU_2100)
    a = post(c, app_headers, [png(1)]).json()["episode_id"]
    clock.set_now(THU_2100 + timedelta(hours=8, minutes=1))
    b = post(c, app_headers, [png(2)]).json()["episode_id"]
    assert a != b


def test_shared_at_clamped(mock_llm, app_headers):
    household()
    c = client()
    clock.set_now(THU_2100)
    ep = post(c, app_headers, [png(1)], shared_at="2026-10-10T09:00:00+09:00").json()["episode_id"]
    assert _episode(ep).shared_at == THU_2100 - timedelta(days=1)
    ep2 = post(c, app_headers, [png(2)], hid="h_042", shared_at="2026-10-16T09:00:00+09:00").json()["episode_id"]
    assert ep2 == ep or _episode(ep2).shared_at == THU_2100


def test_bad_requests(mock_llm, app_headers):
    household()
    c = client()
    four = post(c, app_headers, [png(i) for i in range(4)])
    assert (four.status_code, four.json()["code"]) == (400, "invalid_image")
    gif = c.post("/v1/orders", data={"household_id": "h_042"},
                 files=[("images", ("a.gif", b"GIF89a....", "image/gif"))], headers=app_headers)
    assert (gif.status_code, gif.json()["code"]) == (400, "invalid_image")
    big = post(c, app_headers, [png(1) + b"\0" * (5 * 1024 * 1024)])
    assert big.status_code == 400
    none = c.post("/v1/orders", data={"household_id": "h_042"}, headers=app_headers)
    assert none.json()["code"] == "invalid_image"
    unknown = post(c, app_headers, [png(1)], hid="h_999")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "not_found")
    bad_id = post(c, app_headers, [png(1)], hid="house")
    assert (bad_id.status_code, bad_id.json()["code"]) == (422, "validation_error")
    no_token = post(c, {}, [png(1)])
    assert no_token.status_code == 401
    for r in (four, gif, big, none, unknown, bad_id, no_token):
        validate(r.json(), "error.json")
    with session_scope() as s:
        assert s.execute(select(Episode)).first() is None


def test_t7_zero_items_read_failed(mock_llm, app_headers):
    household()
    c = client()
    img = png(5)
    record_s1(mock_llm, [img], output={"items": [], "orders": []})
    clock.set_now(THU_2100)
    ep = post(c, app_headers, [img]).json()["episode_id"]
    run_quiet(ep, THU_2100 + timedelta(minutes=11))
    assert _episode(ep).status == "read_failed"
    assert mock_llm.calls("s1") == 1                          # items: [] is a valid answer, no retry


def test_t7_llm_fails_twice_read_failed(mock_llm, app_headers):
    household()
    c = client()
    img = png(5)
    record_s1(mock_llm, [img], timeout=True)
    clock.set_now(THU_2100)
    ep = post(c, app_headers, [img]).json()["episode_id"]
    run_quiet(ep, THU_2100 + timedelta(minutes=11))
    assert _episode(ep).status == "read_failed"
    assert mock_llm.calls("s1") == 2


def test_one_bad_item_dropped_alone_and_retry_when_none_survive(mock_llm, app_headers):
    from spira_server.llm import prompts
    from spira_server.llm.client import retry_text

    from .s1_helpers import user_text

    household()
    c = client()
    a, b = png(1), png(2)
    good = {"name": "OO 우유 1L", "type": "우유", "group": "음·식료품", "qty": 1}
    bad = {"name": "파티 접시", "type": "접시", "group": "파티용품", "qty": 1}
    record_s1(mock_llm, [a], output={"items": [good, bad]})
    clock.set_now(THU_2100)
    ep1 = post(c, app_headers, [a]).json()["episode_id"]
    run_quiet(ep1, THU_2100 + timedelta(minutes=11))
    assert [i.type for i in _items(ep1)] == ["우유"]
    assert mock_llm.calls("s1") == 1

    record_s1(mock_llm, [b], output={"items": [bad]})
    retry = user_text(1) + "\n\n" + retry_text(prompts.text("s1_retry.txt"),
                                               ['물건 1의 group "파티용품"은 상품군 목록에 없다'])
    mock_llm.record("s1", prompts.system("s1"), retry, [b],
                    output={"items": [{**bad, "group": "생활용품 – 휴지·위생, 파티용품"}]})
    clock.set_now(THU_2100 + timedelta(hours=9))
    ep2 = post(c, app_headers, [b]).json()["episode_id"]
    run_quiet(ep2, THU_2100 + timedelta(hours=9, minutes=11))
    assert [i.type for i in _items(ep2)] == ["접시"]
    assert mock_llm.calls("s1") == 3


def test_t6_and_t55_masking(mock_llm, app_headers):
    household()
    c = client()
    img = png(3)
    record_s1(mock_llm, [img], output={"items": [
        {"name": "OO 종합감기약 10정", "type": "감기약", "group": None, "qty": 1, "sensitive_kind": "의약품·의약외품"},
        {"name": "임신테스트기 2개입", "type": "테스트기", "group": "생활용품 – 휴지·위생, 파티용품", "qty": 1},
        {"name": "OO 치약 120g", "type": "치약", "group": "생활용품 – 휴지·위생, 파티용품", "qty": 2},
    ]})
    clock.set_now(THU_2100)
    ep = post(c, app_headers, [img]).json()["episode_id"]
    run_quiet(ep, THU_2100 + timedelta(minutes=11))
    items = _items(ep)
    masked = [i for i in items if i.masked]
    assert len(masked) == 2                                   # LLM kind, and the word list only (임신테스트)
    assert all(i.name is None and i.type is None and i.attributes is None for i in masked)
    assert [i.type for i in items if not i.masked] == ["치약"]

    img2 = png(4)
    record_s1(mock_llm, [img2], output={"items": [
        {"name": "OO 감기약 시럽", "type": "시럽", "group": None, "qty": 1},
    ]})
    clock.set_now(THU_2100 + timedelta(hours=9))
    ep2 = post(c, app_headers, [img2]).json()["episode_id"]
    run_quiet(ep2, THU_2100 + timedelta(hours=9, minutes=11))
    e = _episode(ep2)                                         # T55: all masked -> judged, nothing else
    assert (e.status, e.judged, e.intent["none_reason"], e.stage) == ("judged", True, "all_masked", "done")


def test_t44_crash_during_s1_keeps_images(mock_llm, app_headers):
    household()
    c = client()
    img = png(7)
    clock.set_now(THU_2100)
    ep = post(c, app_headers, [img]).json()["episode_id"]
    clock.set_now(THU_2100 + timedelta(minutes=11))
    try:
        s1_extract.on_quiet(ep)                              # nothing recorded -> the call raises (a crash)
    except LookupError:
        pass
    assert _items(ep) == []
    with session_scope() as s:
        [image] = s.execute(select(EpisodeImage)).scalars().all()
        assert image.read is False
    import os
    assert os.path.exists(image.path)

    scheduler.clear()
    assert s1_extract.recover() == [ep]                      # restart: rescheduled at max(quiet_due, now)
    assert scheduler.pending[f"quiet:{ep}"] == THU_2100 + timedelta(minutes=11)
    record_s1(mock_llm, [img], output={"items": [{"name": "우유 1L", "type": "우유", "group": "음·식료품", "qty": 1}]})
    s1_extract.on_quiet(ep)
    assert [i.type for i in _items(ep)] == ["우유"]


def test_capture_after_judging_marks_rerun_and_merges(mock_llm, app_headers):
    household()
    c = client()
    a, b = png(1), png(2)
    record_s1(mock_llm, [a], output={"items": [{"name": "우유 1L", "type": "우유", "group": "음·식료품", "qty": 1}]})
    record_s1(mock_llm, [b], output={"items": [
        {"name": "서울우유 1L", "type": "우유", "group": "음·식료품", "qty": 1},
        {"name": "우유 1L", "type": "우유", "group": "음·식료품", "qty": 1},
        {"name": "식빵", "type": "식빵", "group": "음·식료품", "qty": 1}]})
    clock.set_now(THU_2100)
    ep = post(c, app_headers, [a]).json()["episode_id"]
    run_quiet(ep, THU_2100 + timedelta(minutes=11))
    with session_scope() as s:
        e = s.get(Episode, ep)
        e.judged, e.status = True, "judged"                  # as if S2-S5 ran
    clock.set_now(THU_2100 + timedelta(hours=2, minutes=30))
    assert post(c, app_headers, [b]).json() == {"episode_id": ep, "status": "judged"}
    run_quiet(ep, THU_2100 + timedelta(hours=2, minutes=41))
    assert [i.name for i in _items(ep)] == ["우유 1L", "서울우유 1L", "식빵"]   # different names stay apart
    e = _episode(ep)
    assert (e.status, e.rerun_pending) == ("judged", True)   # re-run itself comes with spec §14


def test_same_order_number_goes_to_its_episode(mock_llm, app_headers):
    household()
    c = client()
    a, b = png(1), png(2)
    record_s1(mock_llm, [a], output={"items": [{"name": "우유 1L", "type": "우유", "group": "음·식료품",
                                                 "qty": 1, "order_no": "A1"}],
                                      "orders": [{"order_no": "A1", "mall": "쿠팡", "eta": None}]})
    record_s1(mock_llm, [b], output={"items": [{"name": "식빵", "type": "식빵", "group": "음·식료품",
                                                 "qty": 1, "order_no": "A1"}]})
    clock.set_now(THU_2100)
    ep_a = post(c, app_headers, [a]).json()["episode_id"]
    run_quiet(ep_a, THU_2100 + timedelta(minutes=11))
    clock.set_now(THU_2100 + timedelta(hours=9))
    ep_b = post(c, app_headers, [b]).json()["episode_id"]
    assert ep_b != ep_a
    run_quiet(ep_b, THU_2100 + timedelta(hours=9, minutes=11))
    assert [i.type for i in _items(ep_a)] == ["우유", "식빵"]
    assert _items(ep_b) == []
