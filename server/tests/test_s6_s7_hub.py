"""S6 hub events and execution results, S7 observation and memory (spec §11.5, §11.8, §12.2, §12.4, §13), through
the routes: the whole ep_9031 timeline (contracts/fixtures/ep_9031/timeline.md) ends in card.final.json,
case_row.json and memory.json. Plus the demo story clock and moments (§12.6)."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from spira_contracts.validate import validate
from sqlalchemy import select

from spira_server import clock, demo_clock
from spira_server.db.engine import session_scope
from spira_server.db.models import Card, Case, Episode, Plan, Task, Window
from spira_server.main import create_app
from spira_server.pipeline import s5_plan, s7_observe
from spira_server.pipeline.s5_cards import card_body

from . import s5_helpers as h
from .factories import fixture, hub_key
from .s4_helpers import JUDGED, ep9031, output

ACKED = clock.parse("2026-10-15T21:11:55+09:00")
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


def _at(monkeypatch, value):
    t = clock.parse(value) if isinstance(value, str) else value
    monkeypatch.setattr(clock, "now", lambda: t)
    return t


def _timeline():
    """Events and execution results of the fixture in time order (events first on equal times)."""
    out = [(e["at"], 0, "event", e) for e in fixture("ep_9031/events.json")]
    out += [(x["at"], 1, "execution", x) for x in fixture("ep_9031/executions.json")]
    return [(kind, body) for _, _, kind, body in sorted(out, key=lambda r: (clock.parse(r[0]), r[1]))]


def _card(ep) -> dict:
    with session_scope() as s:
        return card_body(s, s.execute(select(Card).where(Card.episode_id == ep)).scalar_one())


def test_ep9031_timeline_to_final_card_and_memory(client, app_headers, ep, monkeypatch):
    key = {"X-API-Key": hub_key()}
    _at(monkeypatch, ACKED)
    assert client.post(f"/v1/hub/plans/{ep}/ack", json=fixture("ep_9031/ack.v1.json"), headers=key).status_code == 204
    _at(monkeypatch, V2_AT)
    [reaction] = fixture("ep_9031/reactions.json")
    assert client.post("/v1/cards/nc_331/reactions", json=reaction, headers=app_headers).status_code == 200

    for kind, body in _timeline():
        _at(monkeypatch, clock.parse(body["at"]) + timedelta(seconds=1))
        if kind == "event":
            r = client.post("/v1/hub/events", json=[body], headers=key)
            assert r.status_code == 200, r.json()
            validate(r.json(), "event_response.json")
            assert r.json()["accepted"] == [body["event_id"]] and not r.json()["rejected"]
            if body["type"] == "package.brought_in":                        # §12.4: fridge notices released -> v3
                assert r.json()["plans_changed"] is True
                with session_scope() as s:
                    assert s.get(Plan, (ep, 3)).body["tasks"] == fixture("ep_9031/plan.v3.json")["tasks"]
        else:
            r = client.post("/v1/hub/executions", json=body, headers=key)
            assert (r.status_code, r.json()) == (200, {"duplicate": False}), r.json()
        s7_observe.run_jobs()
        if body["at"].startswith("2026-10-17T13:30:06"):                    # safety line done, window open
            lines = {x["task_id"]: x for x in _card(ep)["lines"]}
            assert lines["t_safe#2"]["state"] == "done" and lines["t_mood#3"]["state"] == "scheduled"
            with session_scope() as s:
                w = s.execute(select(Window).where(Window.episode_id == ep)).scalar_one()
                assert (w.status, clock.iso(w.start_at)) == ("open", "2026-10-17T13:30:05+09:00")
        if body.get("event_id") == "ev_9410":                               # light changed by the user
            lines = {x["task_id"]: x for x in _card(ep)["lines"]}
            assert lines["t_mood#3"]["state"] == "user_changed"

    _at(monkeypatch, "2026-10-17T17:50:16+09:00")
    s7_observe.run_jobs()
    card = _card(ep)
    validate(card, "card.json")
    want = fixture("ep_9031/card.final.json")
    for c in (card, want):
        c.pop("updated_at"), c.pop("notify")
    assert card == want

    with session_scope() as s:
        row = s.get(Case, "home_h_042_ep_9031_1")
        got = {c: getattr(row, c) for c in ("case_id", "source", "household_id", "items", "intent_id", "intent_text",
                                             "situation", "when", "household", "kb_version", "home_did", "verdict",
                                             "task_feedback")}
        w = s.execute(select(Window).where(Window.episode_id == ep)).scalar_one()
        assert (w.status, w.end_reason, w.memory, w.verdict) == ("closed", "event_end", "written", "match")
    assert got == fixture("ep_9031/case_row.json")

    r = client.get("/v1/households/h_042/memory", headers=app_headers)
    assert r.status_code == 200
    validate(r.json(), "memory.json")
    assert r.json() == fixture("ep_9031/memory.json")

    # every task done with and every restore in -> the episode closes (§11.8)
    _at(monkeypatch, "2026-10-17T20:00:01+09:00")
    s7_observe.run_jobs()
    with session_scope() as s:
        statuses = {t.task_id: t.status for t in s.execute(select(Task).where(Task.episode_id == ep)).scalars()}
        assert statuses == {"t_clean#1": "cancelled", "t_safe#2": "ended", "t_mood#3": "ended",
                            "t_oven#4": "ended", "t_fridge#5": "ended", "t_fridge#6": "ended"}
        assert s.get(Episode, ep).status == "closed"

    assert client.delete("/v1/households/h_042/memory/home_h_042_ep_9031_1", headers=app_headers).status_code == 204
    assert client.get("/v1/households/h_042/memory", headers=app_headers).json()["intents"] == []
    assert client.delete("/v1/households/h_042/memory/home_h_042_ep_9031_1",
                         headers=app_headers).status_code == 404


def test_events_one_by_one_duplicates_and_rejections(client, ep, monkeypatch):
    key = {"X-API-Key": hub_key()}
    _at(monkeypatch, "2026-10-16T18:05:11+09:00")
    package = fixture("ep_9031/events.json")[0]
    bad = {**package, "event_id": "ev_bad", "type": "light.changed", "source": "light_01", "payload": {}}
    unknown = {**fixture("ep_9031/events.json")[1], "event_id": "ev_unknown", "source": "toaster_09"}
    other = {**package, "event_id": "ev_other", "household_id": "h_999"}
    r = client.post("/v1/hub/events", json=[package, bad, unknown, other, {"no": "id"}], headers=key)
    assert r.status_code == 200
    body = r.json()
    validate(body, "event_response.json")
    assert body["accepted"] == ["ev_9101"] and body["plans_changed"] is True
    assert [(x["event_id"], x["code"]) for x in body["rejected"]] == [
        ("ev_bad", "validation_error"), ("ev_unknown", "validation_error"), ("ev_other", "forbidden"),
        ("4", "validation_error")]
    again = client.post("/v1/hub/events", json=[package], headers=key).json()
    assert again == {"accepted": ["ev_9101"], "rejected": [], "plans_changed": False}     # duplicate: no v4
    with session_scope() as s:
        assert s.get(Episode, ep).plan_version == 2
    assert client.post("/v1/hub/events", json={"events": [package]}, headers=key).status_code == 422
    assert client.post("/v1/hub/events", json=[package]).status_code == 401


def test_execution_checks_and_late_start_of_a_cancelled_task(client, app_headers, ep, monkeypatch):
    key = {"X-API-Key": hub_key()}
    run = copy.deepcopy(fixture("ep_9031/executions.json")[2])               # t_safe#2 cooktop child_lock
    run["plan_version"] = 1
    _at(monkeypatch, "2026-10-17T13:30:06+09:00")
    assert client.post("/v1/hub/executions", json={**run, "cmd": "heat"}, headers=key).status_code == 422
    assert client.post("/v1/hub/executions", json={**run, "plan_version": 9}, headers=key).status_code == 404
    assert client.post("/v1/hub/executions", json={**run, "status": "nope"}, headers=key).status_code == 422
    # the user stops the card while the hub is already running the safety task
    assert client.post("/v1/cards/nc_331/reactions", json={"reaction": "stop"}, headers=app_headers
                       ).status_code == 200
    with session_scope() as s:
        assert s.get(Task, (ep, "t_safe#2")).restore is False
        assert s.get(Episode, ep).plan_version == 2
    r = client.post("/v1/hub/executions", json=run, headers=key)
    assert r.json() == {"duplicate": False}
    with session_scope() as s:
        task = s.get(Task, (ep, "t_safe#2"))
        assert task.restore is True and task.started_at is not None
        plan = s.get(Plan, (ep, 3)).body
        assert {"task_id": "t_safe#2", "restore": True} in plan["cancelled"]
    assert client.post("/v1/hub/executions", json=run, headers=key).json() == {"duplicate": True}
    with session_scope() as s:
        assert s.get(Episode, ep).plan_version == 3


def test_line_blocked_note_and_never_fired_line(client, ep, monkeypatch):
    key = {"X-API-Key": hub_key()}
    blocked = copy.deepcopy(fixture("ep_9031/executions.json")[6])           # t_oven#4
    blocked.update(plan_version=1, status="blocked", reason="in_use_by_person", result_id="rs_7001")
    _at(monkeypatch, "2026-10-17T14:00:04+09:00")
    assert client.post("/v1/hub/executions", json=blocked, headers=key).status_code == 200
    lines = {x["task_id"]: x for x in _card(ep)["lines"]}
    assert (lines["t_oven#4"]["state"], lines["t_oven#4"]["note"]) == ("blocked", "사용 중이라 실행하지 않았어요")
    # no guest ever arrived: the mood line's window passed with no run -> ended, shown dropped (§11.8)
    _at(monkeypatch, "2026-10-17T17:00:01+09:00")
    s7_observe.end_tasks()
    lines = {x["task_id"]: x for x in _card(ep)["lines"]}
    assert (lines["t_mood#3"]["state"], lines["t_mood#3"]["note"]) == ("dropped", "준비하지 않았어요")
    # nothing confirmed the intent: the window closes at end_due as unconfirmed
    _at(monkeypatch, "2026-10-17T20:00:01+09:00")
    s7_observe.run_jobs()
    with session_scope() as s:
        w = s.execute(select(Window).where(Window.episode_id == ep)).scalar_one()
        assert (w.status, w.end_reason, w.verdict, w.memory) == ("closed", "end_due", "unconfirmed", "written")


# ------------------------------------------------------------------------------------------- demo clock (§12.6)

class Wall:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


@pytest.fixture
def story(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    from spira_server.config import get_config
    from spira_server.settings import get_settings

    get_settings.cache_clear()
    get_config.cache_clear()
    wall = Wall(clock.parse("2026-10-15T21:12:00+09:00"))
    demo_clock.clear()
    demo_clock._clock = demo_clock.StoryClock(wall)
    yield wall
    demo_clock.clear()
    get_settings.cache_clear()
    get_config.cache_clear()


def test_demo_clock_ramps_and_moments(client, app_headers, ep, story):
    r = client.get("/v1/demo/clock")                                          # no auth: the hub polls it
    assert r.status_code == 200
    c = r.json()
    assert (c["version"], c["rate"], c["ramp_until"], c["now"]) == (1, 1.0, None, "2026-10-15T21:12:00.000+09:00")
    assert client.post("/v1/demo/clock", json={"advance_to": "2026-10-15T21:00:00+09:00"},
                       headers=app_headers).status_code == 400                # never backwards
    assert client.post("/v1/demo/clock", json={"advance_to": "2026-10-16T00:00:00+09:00"}).status_code == 401

    m = client.get("/v1/demo/moments", params={"episode_id": ep}, headers=app_headers).json()
    assert [(x["at"], x["kind"], x["event"], x["task_ids"]) for x in m] == [
        ("2026-10-17T12:30:00+09:00", "time", None, ["t_clean#1"]),
        ("2026-10-17T13:30:00+09:00", "time", None, ["t_safe#2"]),
        ("2026-10-17T13:30:00+09:00", "time", "guest_arrived", ["t_mood#3"]),
        ("2026-10-17T14:00:00+09:00", "time", None, ["t_oven#4"]),
        ("2026-10-17T17:00:00+09:00", "event", "event_end", [])]
    assert client.get("/v1/demo/moments", headers=app_headers).json() == []

    r = client.post("/v1/demo/clock/next", params={"episode_id": ep}, json={"over_seconds": 4},
                    headers=app_headers)
    assert r.status_code == 200 and r.json()["task_ids"] == ["t_clean#1"]
    c = client.get("/v1/demo/clock").json()
    assert c["version"] == 2 and c["ramp_until"] == "2026-10-15T21:12:04.000+09:00"
    story.at += timedelta(seconds=4)                                          # ramp over: 20 s before 12:30
    assert demo_clock.get().now() == clock.parse("2026-10-17T12:29:40+09:00")
    story.at += timedelta(seconds=10)                                         # then 1×
    assert demo_clock.get().now() == clock.parse("2026-10-17T12:29:50+09:00")

    for _ in range(3):
        client.post("/v1/demo/clock/next", params={"episode_id": ep}, headers=app_headers)
        story.at += timedelta(seconds=6)
    assert demo_clock.get().now() == clock.parse("2026-10-17T17:00:00+09:00")
    r = client.post("/v1/demo/clock/next", params={"episode_id": ep}, headers=app_headers)
    assert (r.status_code, r.json()["message"]) == (404, "No story moments remain")

    demo_clock.reset()
    assert demo_clock.get().now() == story.at and demo_clock.get().state.version == 6


def test_demo_clock_is_404_without_demo_mode(client, app_headers):
    assert client.get("/v1/demo/clock").status_code == 404
    assert client.get("/v1/demo/moments", headers=app_headers).status_code == 404
