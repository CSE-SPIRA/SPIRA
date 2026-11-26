"""GET /v1/episodes/{id} and …/rationale (spec §12.2): stored values only, readable stage by stage while judging."""

import pytest
from fastapi.testclient import TestClient
from spira_contracts.validate import validate
from sqlalchemy import select

from spira_server.db.engine import session_scope
from spira_server.db.models import Episode
from spira_server.main import create_app
from spira_server.pipeline import s5_plan

from . import s5_helpers as h
from .factories import fixture
from .s4_helpers import JUDGED, ep9031, episode, household, output


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(start_background=False))


def _context() -> dict:
    """The S2 context of ep_9031, written back from the rationale fixture's evidence."""
    ev = fixture("ep_9031/rationale.json")["evidence"]
    examples = [{"case_id": e["case_id"], "items": e["items"], "intent_id": e["intent_id"],
                 "intent_text": e["intent_text"], "situation": {}, "calendar_tags": [], "case_household_types": []}
                for e in ev["kb_examples"]]
    counts = [{**r, "share": 0.1, "base_share": 0.02} for r in ev["kb_counts"]]
    counts.append({"intent_id": "home_party", "name": "홈파티", "n": 0, "share": 0.0, "base_share": 0.05})
    return {"for_intent": {
        "order_time": {"shared_at": "2026-10-15T21:00:08+09:00"},
        "this_home": {"household_types": ["3~4인"], "calendar": ev["calendar"], "unusual_items": ev["unusual_items"]},
        "kb_neighbors": {"similar_count": 12, "intent_counts": counts, "examples": examples, "note": None,
                         "base_total": 1000},
    }, "snapshot": [e["case_id"] for e in ev["kb_examples"]]}


def _set(ep: str, **values) -> None:
    with session_scope() as s:
        row = s.execute(select(Episode).where(Episode.id == ep).with_for_update()).scalar_one()
        for k, v in values.items():
            setattr(row, k, v)


def test_ep9031_episode_and_rationale(client, app_headers, mock_llm):
    ep = ep9031()
    _set(ep, context=_context())
    h.restart_card_ids(331)
    s5_plan.finalize(ep, h.s4_for(mock_llm, ep, output(), JUDGED), now=JUDGED)

    r = client.get(f"/v1/episodes/{ep}", headers=app_headers)
    assert r.status_code == 200
    body = r.json()
    validate(body, "episode.json")
    want = fixture("ep_9031/episode.json")
    assert [(i["item_id"], i["type"], i["qty"]) for i in body["items"]] == \
        [(i["item_id"], i["type"], i["qty"]) for i in want["items"]]
    assert body["card_ids"] == ["nc_331"] and body["masked_count"] == 0 and body["item_count"] == 9
    assert {(t["item"], t["kind"]) for t in body["item_tasks"]} == {(t["item"], t["kind"]) for t in want["item_tasks"]}
    assert all(t["state"] == "scheduled" for t in body["item_tasks"])          # nothing ran yet

    r = client.get(f"/v1/episodes/{ep}/rationale", headers=app_headers)
    assert r.status_code == 200
    body = r.json()
    validate(body, "rationale.json")
    want = fixture("ep_9031/rationale.json")
    got, exp = body["intents"][0], want["intents"][0]
    assert (got["card_id"], got["intent_id"], got["calendar_event_id"], got["calendar_tags"]) == \
        ("nc_331", "kid_birthday_party", "c1", ["생일"])
    assert got["basis"] == exp["basis"] and got["situation"] == exp["situation"]
    assert body["evidence"]["calendar"] == want["evidence"]["calendar"]
    assert body["evidence"]["unusual_items"] == want["evidence"]["unusual_items"]
    assert body["evidence"]["kb_counts"] == want["evidence"]["kb_counts"]          # n = 0 row left out
    assert [e["overlap"] for e in body["evidence"]["kb_examples"]] == \
        [e["overlap"] for e in want["evidence"]["kb_examples"]]
    assert body["unbundled"] == ["세탁 세제", "로션"] and body["none_reason"] is None
    assert [t["task_id"] for t in body["tasks"]] == [t["task_id"] for t in want["tasks"]]
    assert body["tasks"][0]["devices"] == want["tasks"][0]["devices"]
    assert body["executions"] == [] and body["observations"][0]["card_id"] == "nc_331"


def test_rationale_fills_stage_by_stage(client, app_headers):
    household()
    ep = episode()
    _set(ep, intent=None)                                       # S1 stored the items, S2 not yet

    r = client.get(f"/v1/episodes/{ep}", headers=app_headers)
    assert r.status_code == 200 and len(r.json()["items"]) == 9 and r.json()["card_ids"] == []
    validate(r.json(), "episode.json")
    r = client.get(f"/v1/episodes/{ep}/rationale", headers=app_headers)
    assert r.status_code == 404 and r.json()["code"] == "not_found"

    _set(ep, context=_context())                                # S2 done
    body = client.get(f"/v1/episodes/{ep}/rationale", headers=app_headers).json()
    validate(body, "rationale.json")
    assert body["intents"] == [] and body["none_reason"] is None and body["tasks"] == []
    assert body["evidence"]["kb_counts"][0]["intent_id"] == "kid_birthday_party"

    from .s4_helpers import intent_ep9031
    _set(ep, intent=intent_ep9031())                            # S3 done, S5 not yet
    body = client.get(f"/v1/episodes/{ep}/rationale", headers=app_headers).json()
    validate(body, "rationale.json")
    assert body["intents"][0]["intent_id"] == "kid_birthday_party" and body["intents"][0]["card_id"] is None


def test_kb_off_and_note_only(client, app_headers):
    household()
    ep = episode()
    _set(ep, intent=None, context={"for_intent": {"order_time": {"shared_at": "2026-10-15T21:00:08+09:00"}}, "snapshot": []})
    ev = client.get(f"/v1/episodes/{ep}/rationale", headers=app_headers).json()["evidence"]
    assert ev == {"calendar": [], "unusual_items": None, "kb_counts": None, "kb_examples": [], "kb_note": None}

    _set(ep, context={"for_intent": {"kb_neighbors": {"similar_count": 2, "note": "비슷한 사례가 거의 없음"}}})
    ev = client.get(f"/v1/episodes/{ep}/rationale", headers=app_headers).json()["evidence"]
    assert ev["kb_counts"] == [] and ev["kb_note"] == "비슷한 사례가 거의 없음"


def test_unknown_episode_and_auth(client, app_headers):
    assert client.get("/v1/episodes/ep_404", headers=app_headers).status_code == 404
    assert client.get("/v1/episodes/ep_404/rationale", headers=app_headers).status_code == 404
    assert client.get("/v1/episodes/ep_404").status_code == 401
