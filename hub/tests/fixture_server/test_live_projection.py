"""Live App-facing state changes from the HUB-17 event and result bodies."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from . import create_app
from .replay import Replay
from .test_fixture_server import ACK, APP_HOUSEHOLD, EPISODE, HEADERS, ContractClient
from .test_scene_support import SELECT, upload


@pytest.fixture
def birthday(monkeypatch):
    http = TestClient(create_app(scene_controls=True, demo_mode=True), headers=HEADERS)
    client = ContractClient(http, "ep_9031", set())
    assert http.post(SELECT, json={
        "episode_id": "ep_9031", "starts_in_seconds": 240, "duration_seconds": 120,
    }).status_code == 202
    assert upload(http, "birthday").status_code == 202
    plan = client.pull()["plans"][0]
    wall = datetime.fromisoformat(plan["sent_at"])

    def advance(at):
        nonlocal wall
        wall = at

    monkeypatch.setattr(Replay, "now", lambda replay: max(replay.clock, wall))
    return client, advance, plan


def test_birthday_line_progress_and_end_follow_hub_17(birthday):
    client, advance, plan = birthday
    request = client.request
    events = {event["event_id"]: event for event in client.fixture("events.json")}
    executions = {result["result_id"]: result for result in client.fixture("executions.json")}
    tasks = {task["task_id"]: task for task in plan["tasks"]}
    safety = datetime.fromisoformat(tasks["t_safe#2"]["trigger"]["time"])
    starts = datetime.fromisoformat(tasks["t_oven#4"]["trigger"]["time"])
    end = starts + timedelta(minutes=2, seconds=1)
    sent = datetime.fromisoformat(plan["sent_at"])
    poll = client.cards()

    def card_change():
        nonlocal poll
        current = client.cards(since=poll["server_time"])
        assert len(current["cards"]) == 1
        card = current["cards"][0]
        assert card["notify"] is False
        assert datetime.fromisoformat(card["updated_at"]) > datetime.fromisoformat(poll["server_time"])
        poll = current
        return card

    def event(event_id, when, **changes):
        advance(when)
        return request("POST", "/v1/hub/events", json=[
            dict(events[event_id], at=when.isoformat(), **changes),
        ])

    def result(result_id, when, **changes):
        advance(when)
        return request("POST", "/v1/hub/executions", json=dict(
            executions[result_id], plan_version=3, at=when.isoformat(), **changes,
        ))

    assert poll["cards"][0]["summary"] == {"done": 0, "total": 4, "waiting_for": None}
    assert client.react(client.fixture("reactions.json")[0])["lines"][0]["state"] == "off"
    assert card_change()["summary"] == {"done": 0, "total": 3, "waiting_for": None}
    assert event("ev_9101", sent + timedelta(seconds=4))["plans_changed"] is True
    result("rs_5001", sent + timedelta(seconds=5))
    result("rs_5002", sent + timedelta(seconds=6))
    event("ev_9102", sent + timedelta(seconds=7))
    assert [task["state"] for task in request("GET", EPISODE)["item_tasks"]] == ["done", "done"]

    advance(safety)
    assert card_change()["summary"]["waiting_for"] == "guest_arrived"
    event("ev_9211", safety + timedelta(seconds=3))
    event("ev_9212", safety + timedelta(seconds=4))
    result("rs_5005", safety + timedelta(seconds=5))
    assert card_change()["lines"][1]["state"] == "running"
    result("rs_5006", safety + timedelta(seconds=6))
    assert card_change()["lines"][1]["state"] == "done"

    guests = safety + timedelta(seconds=30)
    event("ev_9303", guests)
    assert card_change()["summary"]["waiting_for"] is None
    event("ev_9304", guests + timedelta(seconds=1))
    result("rs_5011", guests + timedelta(seconds=2))
    assert card_change()["lines"][2]["state"] == "running"
    event("ev_9305", guests + timedelta(seconds=3))
    result("rs_5012", guests + timedelta(seconds=4))
    assert card_change()["lines"][2]["state"] == "done"

    result("rs_5020", starts + timedelta(seconds=3))
    assert card_change()["summary"] == {"done": 3, "total": 3, "waiting_for": None}
    event("ev_9350", starts + timedelta(seconds=20))
    oven = card_change()["lines"][3]
    assert (oven["state"], oven["end_state"]) == ("done", "none")
    light_change = events["ev_9410"]["payload"]
    event("ev_9410", starts + timedelta(seconds=50), payload=dict(light_change, by="unknown"))
    assert client.cards(since=poll["server_time"])["cards"] == []
    events["ev_9410"]["event_id"] = "ev_light_user"
    event("ev_9410", starts + timedelta(seconds=51))
    assert card_change()["lines"][2]["state"] == "user_changed"

    when = end + timedelta(seconds=15)
    # C-4 can arrive ahead of the C-3 event which establishes the end.
    result("rs_5090", when)
    assert client.cards(since=poll["server_time"])["cards"] == []
    event("ev_9500", end)
    mood = card_change()["lines"][2]
    assert (mood["state"], mood["end_state"]) == ("user_changed", "kept_user_change")
    assert request("GET", EPISODE)["status"] == "notified"
    result("rs_5091", when)
    final = card_change()
    assert [line["end_state"] for line in final["lines"]] == [None, "restored", "kept_user_change", "none"]
    assert request("GET", EPISODE)["status"] == "closed"
    assert request("GET", f"{APP_HOUSEHOLD}/memory")["intents"] == []


@pytest.mark.parametrize("status,reason,expected", [
    ("unverifiable", None, "unknown"),
    ("failed", None, "failed"),
    ("blocked", "plan_unconfirmed", "blocked"),
])
def test_live_run_outcome_is_visible_and_retries_do_not_move_the_cursor(birthday, status, reason, expected):
    client, advance, plan = birthday
    poll = client.cards()
    result = client.fixture("executions.json")[6]
    starts = datetime.fromisoformat(poll["cards"][0]["starts_at"])
    advance(starts)
    result.update(plan_version=plan["plan_version"], status=status, reason=reason, at=starts.isoformat())
    result.pop("observed")
    route = "/v1/hub/executions"
    assert client.request("POST", route, json=result) == {"duplicate": False}
    changed = client.cards(since=poll["server_time"])
    line = changed["cards"][0]["lines"][3]
    assert (line["state"], line["note"]) == (expected, reason)
    assert client.request("POST", route, json=result) == {"duplicate": True}
    assert client.cards(since=changed["server_time"])["cards"] == []


@pytest.mark.parametrize("first_status,second_status,started,expected", [
    ("failed", "failed", False, "failed"),
    ("failed", "completed", False, "partial"),
    ("failed", "blocked", True, "failed"),
    ("unverifiable", "unknown", False, "unknown"),
    ("unverifiable", "blocked", False, "blocked"),
])
def test_two_action_line_waits_for_final_results(birthday, first_status, second_status, started, expected):
    """server/spec.md §11.5: "some `completed` and every other action final → `partial`";
    "none completed and every action final: any `failed` → `failed`, any `blocked` → `blocked`".
    """
    client, advance, plan = birthday
    first, second = client.fixture("executions.json")[2:4]
    task = plan["tasks"][1]
    safety = datetime.fromisoformat(task["trigger"]["time"])
    advance(safety)
    route = "/v1/hub/executions"
    for result in (first, second):
        result.update(plan_version=plan["plan_version"], at=safety.isoformat())
    if started:
        running = dict(first, result_id="rs_safety_running", status="running")
        running.pop("observed")
        client.request("POST", route, json=running)

    poll = client.cards()
    assert poll["cards"][0]["lines"][1]["state"] == ("running" if started else "scheduled")
    first.update(status=first_status, at=(safety + timedelta(seconds=1)).isoformat())
    first.pop("observed")
    client.request("POST", route, json=first)
    assert client.cards(since=poll["server_time"])["cards"] == []

    second.update(status=second_status, at=(safety + timedelta(seconds=2)).isoformat())
    if second_status != "completed":
        second.pop("observed")
    if second_status == "blocked":
        second["reason"] = "plan_unconfirmed"
    client.request("POST", route, json=second)
    card = client.cards(since=poll["server_time"])["cards"][0]
    assert card["lines"][1]["state"] == expected
    assert card["lines"][1]["note"] == (second.get("reason") if expected == "blocked" else None)
    assert card["summary"]["done"] == int(expected == "partial")


def test_partial_run_and_rejected_ack_use_expected_actions(birthday):
    client, advance, plan = birthday
    result1, result2 = client.fixture("executions.json")[2:4]
    safety = datetime.fromisoformat(plan["tasks"][1]["trigger"]["time"])
    advance(safety)
    result1.update(plan_version=1, at=safety.isoformat())
    result2.update(plan_version=1, at=safety.isoformat(), status="unverifiable")
    result2.pop("observed")
    running = dict(result1, result_id="rs_safety_running", status="running")
    running.pop("observed")
    client.request("POST", "/v1/hub/executions", json=running)
    assert client.cards()["cards"][0]["lines"][1]["state"] == "running"
    for result in (result1, result2):
        client.request("POST", "/v1/hub/executions", json=result)
    late_running = dict(running, result_id="rs_safety_late_running", at=(safety + timedelta(seconds=1)).isoformat())
    client.request("POST", "/v1/hub/executions", json=late_running)
    client.request("POST", ACK, 204, json={
        "plan_version": 1, "status": "admitted",
        "rejected_tasks": [{"task_id": "t_oven#4", "reason": "unsupported_cmd"}],
    })
    card = client.cards()["cards"][0]
    assert [card["lines"][i]["state"] for i in (1, 3)] == ["partial", "failed"]
    assert card["summary"]["done"] == 1


@pytest.mark.parametrize("second_status,expected", [
    ("skipped_user_changed", "withheld"),
    ("unknown", "restore_failed"),
])
def test_restore_priority_at_the_time_fallback(birthday, second_status, expected):
    client, advance, plan = birthday
    safe = plan["tasks"][1]
    starts = datetime.fromisoformat(safe["trigger"]["time"])
    advance(starts)
    client.react(client.fixture("reactions.json")[0])
    for result in client.fixture("executions.json")[2:4]:
        client.request("POST", "/v1/hub/executions", json=dict(result, at=starts.isoformat(), plan_version=2))
    fallback = datetime.fromisoformat(safe["end"]["or_time"])
    advance(fallback)
    polled = client.cards()
    assert polled["cards"][0]["lines"][1]["end_state"] is None
    assert client.request("GET", EPISODE)["status"] == "notified"
    restore = client.fixture("executions.json")[-1]
    restore["items"][0]["status"] = "withheld_end_not_observed"
    restore["items"][1]["status"] = second_status
    restore.update(at=fallback.isoformat(), plan_version=2)
    client.request("POST", "/v1/hub/executions", json=restore)
    line = client.cards(since=polled["server_time"])["cards"][0]["lines"][1]
    assert (line["state"], line["end_state"]) == ("done", expected)
    assert client.request("GET", EPISODE)["status"] == "closed"


def test_stop_waits_for_the_started_lines_restore(birthday):
    client, advance, plan = birthday
    starts = datetime.fromisoformat(plan["tasks"][1]["trigger"]["time"])
    advance(starts)
    result = client.fixture("executions.json")[2]
    client.request("POST", "/v1/hub/executions", json=dict(result, at=starts.isoformat(), plan_version=1))
    stopped = client.react({"reaction": "stop"})
    assert stopped["summary"] == {"done": 0, "total": 0, "waiting_for": None}
    assert stopped["lines"][1]["end_state"] is None
    assert client.request("GET", EPISODE)["status"] == "notified"
    restore = client.fixture("executions.json")[-1]
    restore["items"] = [{"device": "cooktop_01", "status": "not_needed"}]
    restore.update(at=(starts + timedelta(seconds=1)).isoformat(), plan_version=2)
    client.request("POST", "/v1/hub/executions", json=restore)
    card = client.cards(since=stopped["updated_at"])["cards"][0]
    assert (card["lines"][1]["state"], card["lines"][1]["end_state"]) == ("stopped", "restored")
    assert client.request("GET", EPISODE)["status"] == "closed"
