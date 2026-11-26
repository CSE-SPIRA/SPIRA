"""Card reactions (spec §11.7) and the episode list (§12.2): T25 T27 and line_on, through the routes."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from spira_contracts.validate import validate
from sqlalchemy import select

from spira_server import clock
from spira_server.db.engine import session_scope
from spira_server.db.models import CardLine, Episode, Plan, Task
from spira_server.main import create_app
from spira_server.pipeline import s5_plan

from . import s5_helpers as h
from .factories import fixture
from .s4_helpers import JUDGED, ep9031, output

V2_AT = clock.parse("2026-10-16T08:40:12+09:00")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(start_background=False))


@pytest.fixture
def ep(mock_llm) -> str:
    e = ep9031()
    h.restart_card_ids(331)
    s5_plan.finalize(e, h.s4_for(mock_llm, e, output(), JUDGED), now=JUDGED)
    return e


def _react(client, headers, body, card="nc_331"):
    return client.post(f"/v1/cards/{card}/reactions", json=body, headers=headers)


def _plan(ep, version):
    with session_scope() as s:
        p = s.get(Plan, (ep, version))
        return p.body if p else None


def test_t25_line_off_then_line_on(client, app_headers, ep, monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: V2_AT)
    [body] = fixture("ep_9031/reactions.json")
    r = _react(client, app_headers, body)
    assert r.status_code == 200
    card = r.json()
    validate(card, "card.json")
    line = next(x for x in card["lines"] if x["task_id"] == "t_clean#1")
    assert (line["checked"], line["state"], card["notify"]) == (False, "off", False)
    assert _plan(ep, 2) == fixture("ep_9031/plan.v2.json")                     # T25
    assert _react(client, app_headers, body).json() == card                     # already off: nothing new
    assert _plan(ep, 3) is None

    r = _react(client, app_headers, {"reaction": "line_on", "task_id": "t_clean#1"})
    assert r.status_code == 200
    lines = r.json()["lines"]
    assert [x["task_id"] for x in lines][0] == "t_clean#7"                     # new id, same position
    assert (lines[0]["checked"], lines[0]["state"]) == (True, "scheduled")
    plan = _plan(ep, 3)
    assert plan["tasks"][-1]["task_id"] == "t_clean#7"
    assert {"task_id": "t_clean#1", "restore": False} in plan["cancelled"]
    with session_scope() as s:
        assert s.get(Episode, ep).next_task_n == 8
        assert s.get(Task, (ep, "t_clean#1")).status == "cancelled"
        assert s.get(Task, (ep, "t_clean#7")).status == "live"


def test_line_on_after_start_is_409_and_unknown_line_404(client, app_headers, ep):
    _react(client, app_headers, {"reaction": "line_off", "task_id": "t_mood#3"})
    with session_scope() as s:
        s.get(Task, (ep, "t_mood#3")).meta = {"start_uncertain": True}
    r = _react(client, app_headers, {"reaction": "line_on", "task_id": "t_mood#3"})
    assert (r.status_code, r.json()["code"]) == (409, "line_started")
    assert _react(client, app_headers, {"reaction": "line_off", "task_id": "t_nope#9"}).status_code == 404
    assert _react(client, app_headers, {"reaction": "stop"}, card="nc_999").status_code == 404
    assert _react(client, app_headers, {"reaction": "stop", "task_id": "t_mood#3"}).status_code == 422
    assert _react(client, app_headers, {"reaction": "line_off"}).status_code == 422


def test_t27_stop_while_running(client, app_headers, ep):
    with session_scope() as s:
        s.get(Task, (ep, "t_clean#1")).started_at = JUDGED
    r = _react(client, app_headers, {"reaction": "stop"})
    card = r.json()
    assert (card["stopped"], card["buttons"]) == (True, [])
    assert {x["state"] for x in card["lines"]} == {"stopped"}
    with session_scope() as s:
        tasks = {t.task_id: (t.status, t.restore) for t in s.execute(select(Task).where(Task.episode_id == ep)).scalars()}
    assert tasks["t_clean#1"] == ("cancelled", True)
    assert tasks["t_mood#3"] == ("cancelled", False)
    plan = _plan(ep, 2)
    assert {"task_id": "t_clean#1", "restore": True} in plan["cancelled"]
    assert _react(client, app_headers, {"reaction": "line_on", "task_id": "t_clean#1"}).json() == card   # ignored
    assert _plan(ep, 3) is None


def test_episode_list_newest_first_with_cursor(client, app_headers, ep):
    r = client.get("/v1/households/h_042/episodes", headers=app_headers)
    assert r.status_code == 200
    body = r.json()
    validate(body, "episode_list.json")
    [only] = body["episodes"]
    assert (only["episode_id"], only["status"], only["card_ids"], body["next_before"]) == (ep, "notified", ["nc_331"], None)
    assert only["item_count"] > 0
    with session_scope() as s:
        first = s.get(Episode, ep)
        for n, minutes in ((2, 5), (3, 10)):
            s.add(Episode(id=f"ep_90{n}", household_id="h_042", status="received",
                          shared_at=first.shared_at + timedelta(minutes=minutes),
                          received_at=first.shared_at, source_ids=[], judged=False, stage="s1", plan_version=0,
                          next_item_n=1, next_task_n=1, next_card_ordinal=1, rerun_pending=False))
    page = client.get("/v1/households/h_042/episodes", params={"limit": 2}, headers=app_headers).json()
    assert [e["episode_id"] for e in page["episodes"]] == ["ep_903", "ep_902"]
    rest = client.get("/v1/households/h_042/episodes", params={"limit": 2, "before": page["next_before"]},
                      headers=app_headers).json()
    assert ([e["episode_id"] for e in rest["episodes"]], rest["next_before"]) == ([ep], None)
    assert client.get("/v1/households/h_999/episodes", headers=app_headers).status_code == 404
    assert client.get("/v1/households/h_042/episodes", params={"limit": 0}, headers=app_headers).status_code == 422
