"""HTTP checks for opt-in story-clock scene replay."""

import pickle
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from spira_contracts.reaction import Reaction

from . import api, create_app, replay as replay_module
from .moments import QUIET_END
from .replay import JudgmentStage, Replay
from .scene_support import JUDGMENT_SECONDS, NextOrder, live_replay, server_numbers
from .story_clock import StoryClock
from .test_fixture_server import (
    EPISODE,
    HEADERS,
    ContractClient,
    check_schema,
    share_order,
)

CLOCK = "/v1/demo/clock"
SELECT = "/_fixture/scene/next-order"
CALENDAR = "/_fixture/scene/calendar"
ACKS = "/_fixture/scene/acks"
PLANS = "/v1/hub/plans?household=h_042"
CARDS = "/v1/households/h_042/cards"


def upload(client, source, household="h_042"):
    return client.post(
        "/v1/orders",
        data={"household_id": household, "source_id": source},
        files={"images": ("capture.png", b"fixture upload", "image/png")},
    )


def finish_judgment(client):
    now = datetime.fromisoformat(client.get(CLOCK).json()["story_at"])
    due = now + timedelta(seconds=server_numbers()["quiet_s"] + JUDGMENT_SECONDS[JudgmentStage.PUBLISHED])
    assert client.post(CLOCK, json={"set_to": due.isoformat()}).status_code == 200
    return due


def test_scene_selection_publishes_on_the_next_valid_new_order():
    client = TestClient(create_app(scene_controls=True, demo_mode=True), headers=HEADERS)
    assert client.get(CARDS).json()["cards"] == []
    assert client.get(PLANS).json()["plans"] == []
    assert client.post(SELECT, json={"episode_id": "ep_9120"}).status_code == 422
    assert client.post(SELECT, json={"episode_id": "ep_9031", "unexpected": 0}).status_code == 422
    assert client.post(SELECT, json={"episode_id": "ep_9031"}).status_code == 202
    assert client.get(CARDS).json()["cards"] == []
    assert upload(client, "wrong-home", "h_051").status_code == 404
    result = upload(client, "birthday")
    assert result.status_code == 202
    assert result.json() == {"episode_id": "ep_9031", "status": "received"}
    assert client.get(CARDS).json()["cards"] == []
    assert client.get(PLANS).json()["plans"] == []
    finish_judgment(client)
    assert client.get(CARDS).json()["cards"][0]["episode_id"] == "ep_9031"

    ack = {"plan_version": 1, "status": "admitted", "rejected_tasks": []}
    assert client.post("/v1/hub/plans/ep_9031/ack", json=ack).status_code == 204
    assert client.get(ACKS).json() == [ack]

    assert client.post(SELECT, json={"episode_id": "ep_9150"}).status_code == 202
    duplicate = upload(client, "birthday")
    assert duplicate.status_code == 200
    assert duplicate.json()["episode_id"] == "ep_9031"
    assert client.get(CARDS).json()["cards"][0]["episode_id"] == "ep_9031"
    groceries = upload(client, "groceries")
    assert groceries.status_code == 202
    assert groceries.json() == {"episode_id": "ep_9150", "status": "received"}
    finish_judgment(client)
    assert [card["episode_id"] for card in client.get(CARDS).json()["cards"]] == ["ep_9031"]
    assert client.get("/v1/episodes/ep_9150").json()["household_id"] == "h_042"
    assert client.get(PLANS).json()["plans"][0]["plan_id"] == "ep_9150"


def test_default_scene_replays_each_new_order_without_selection():
    client = TestClient(
        create_app(default_scene=NextOrder(episode_id="ep_9031"), demo_mode=True),
        headers=HEADERS,
    )
    assert client.get(CARDS).json()["cards"] == []
    assert client.get(PLANS).json()["plans"] == []
    first = upload(client, "birthday")
    assert first.status_code == 202
    assert first.json() == {"episode_id": "ep_9031", "status": "received"}
    due = finish_judgment(client)
    plan = client.get(PLANS).json()["plans"][0]
    assert plan["plan_id"] == "ep_9031"
    assert plan["sent_at"] == due.isoformat()
    assert client.get(CARDS).json()["cards"][0]["episode_id"] == "ep_9031"

    duplicate = upload(client, "birthday")
    assert duplicate.status_code == 200
    assert duplicate.json() == first.json()
    second = upload(client, "another-birthday")
    assert second.status_code == 202
    assert second.json()["episode_id"] == "ep_90312"
    finish_judgment(client)
    assert client.get(PLANS).json()["plans"][0]["plan_id"] == "ep_90312"


@pytest.mark.parametrize("episode_id", ["ep_9031", "ep_9150"])
def test_scene_order_exposes_rationale_at_first_card_poll(episode_id):
    http = TestClient(create_app(scene_controls=True, demo_mode=True), headers=HEADERS)
    client = ContractClient(http, episode_id, set())
    rationale = f"{EPISODE}/rationale"
    assert http.post(SELECT, json={"episode_id": episode_id}).status_code == 202
    initial = client.cards()
    assert initial["cards"] == []
    assert client.request("GET", rationale, 404)["code"] == "not_found"

    assert share_order(client, 202, "scene-share") == {
        "episode_id": episode_id,
        "status": "received",
    }
    finish_judgment(http)
    cards = client.cards(since=initial["server_time"])["cards"]
    assert [card["card_id"] for card in cards] == client.fixture("episode.json")["card_ids"]
    actual = client.request("GET", rationale)
    original = client.fixture("rationale.json")
    if episode_id == "ep_9031":
        assert actual["evidence"]["calendar"] == original["evidence"]["calendar"]
        assert actual["item_tasks"] == client.request("GET", EPISODE)["item_tasks"]
    else:
        assert actual == original


@pytest.mark.parametrize(("episode_id", "demo_mode"), [("ep_9031", True), ("ep_9150", False)])
def test_live_share_publishes_judgment_in_story_time(episode_id, demo_mode, monkeypatch):
    real_now = datetime.fromisoformat("2026-11-25T12:00:00+09:00")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return real_now.astimezone(tz)

    monkeypatch.setattr(api, "datetime", FrozenDateTime)
    monkeypatch.setattr(replay_module, "datetime", FrozenDateTime)
    http = TestClient(create_app(scene_controls=True, demo_mode=demo_mode), headers=HEADERS)
    client = ContractClient(http, episode_id, set())
    assert http.post(SELECT, json={"episode_id": episode_id}).status_code == 202
    assert upload(http, "staged-order").status_code == 202
    recorded = client.fixture("episode.json")
    rationale = client.fixture("rationale.json")
    initial_tasks = [{**task, "state": "scheduled"} for task in rationale["item_tasks"]]
    shared_at = datetime.fromisoformat(recorded["shared_at"])
    quiet_end = next(moment for moment in http.get("/v1/demo/moments").json() if moment["event"] == QUIET_END)
    assert quiet_end["kind"] == "time"
    assert quiet_end["episode_id"] == episode_id
    assert datetime.fromisoformat(quiet_end["at"]) == shared_at + timedelta(seconds=600)
    rationale_path = f"{EPISODE}/rationale"

    def seek(seconds):
        at = shared_at + timedelta(seconds=seconds)
        assert http.post(CLOCK, json={"set_to": at.isoformat()}).status_code == 200

    def assert_episode(status, *, items=False, judged=False, published=False):
        result = client.request("GET", EPISODE)
        assert result == {
            **recorded, "status": status,
            "items": recorded["items"] if items else [],
            "item_count": recorded["item_count"] if items else 0,
            "masked_count": recorded["masked_count"] if items else 0,
            "item_tasks": initial_tasks if judged else [],
            "card_ids": recorded["card_ids"] if published else [],
        }
        summary, = http.get("/v1/households/h_042/episodes").json()["episodes"]
        assert summary == {key: result[key] for key in ("episode_id", "shared_at", "status", "item_count", "card_ids")}
        if not published:
            assert client.cards()["cards"] == []
            assert client.pull()["plans"] == []

    assert_episode("received")
    seek(1)
    assert_episode("reading")
    seek(5.999)
    assert_episode("reading")
    seek(6)
    assert_episode("reading", items=True)
    assert client.request("GET", rationale_path, 404)["code"] == "not_found"
    seek(600)
    assert_episode("reading", items=True)
    assert client.request("GET", rationale_path, 404)["code"] == "not_found"
    seek(614.999)
    assert client.request("GET", rationale_path, 404)["code"] == "not_found"

    seek(615)
    assert_episode("reading", items=True)
    assert client.request("GET", rationale_path) == {
        **rationale, "intents": [], "none_reason": None, "unbundled": [],
        "tasks": [], "item_tasks": [], "executions": [], "observations": [],
    }
    seek(630)
    assert_episode("reading", items=True)
    assert client.request("GET", rationale_path) == {
        **rationale, "tasks": [], "item_tasks": [], "executions": [], "observations": [],
    }
    for offset in (645, 659.999):
        seek(offset)
        assert_episode("judged", items=True, judged=True)
        assert client.request("GET", rationale_path) == {
            **rationale, "tasks": [{**task, "state": "scheduled"} for task in rationale["tasks"]],
            "item_tasks": initial_tasks, "executions": [], "observations": [],
        }

    seek(660)
    assert_episode("notified" if recorded["card_ids"] else "judged", items=True, judged=True, published=True)
    assert [card["card_id"] for card in client.cards()["cards"]] == recorded["card_ids"]
    plan, = client.pull()["plans"]
    assert plan == {**client.fixture("plan.v1.json"), "sent_at": http.get(CLOCK).json()["story_at"]}


def test_scene_keeps_recorded_calendar_wording_and_task_times():
    recorded = Replay("ep_9031")
    shared = datetime.fromisoformat(recorded.episode.shared_at)
    replay = live_replay(NextOrder(episode_id="ep_9031"), clock=StoryClock(shared))

    assert replay.calendar == recorded.calendar
    assert replay.episode == recorded.episode
    assert replay.plan.tasks == recorded.plan.tasks
    assert replay.card.starts_at == recorded.card.starts_at
    assert replay.card.text == recorded.card.text
    assert replay.card.lines == recorded.card.lines


def test_demo_checkpoint_from_before_observation_tracking_restores_window():
    now = datetime.fromisoformat("2026-10-15T21:01:00+09:00")
    replay = live_replay(NextOrder(episode_id="ep_9031"), clock=StoryClock(now))
    replay.react(Reaction(reaction="line_off", task_id="t_clean#1"))
    window = replay.observation_window
    del replay.observation_window, replay.observation, replay.checked_changed_at

    restored = pickle.loads(pickle.dumps(replay))
    assert restored.observation_window == window
    assert restored.observation is None
    assert restored.checked_changed_at["t_clean#1"] == datetime.fromisoformat(restored.plan.sent_at)


def test_scene_story_times_and_live_revisions():
    client = TestClient(create_app(scene_controls=True, demo_mode=True), headers=HEADERS)
    assert client.post(SELECT, json={"episode_id": "ep_9031"}).status_code == 202
    assert upload(client, "birthday").status_code == 202
    sent = finish_judgment(client)
    plan = client.get(PLANS).json()["plans"][0]
    check_schema(plan, {"$ref": "plan.json"})
    card = client.get(CARDS).json()["cards"][0]
    check_schema(card, {"$ref": "card.json"})
    assert card["updated_at"] == plan["sent_at"] == sent.isoformat()
    assert [line["when"] for line in card["lines"][:2]] == [
        task["trigger"] for task in plan["tasks"][:2]
    ]

    reaction = {"reaction": "line_off", "task_id": "t_clean#1"}
    assert client.post(f"/v1/cards/{card['card_id']}/reactions", json=reaction).status_code == 200
    v2 = client.get(PLANS).json()["plans"][0]
    assert v2["plan_version"] == 2
    assert datetime.fromisoformat(v2["sent_at"]) > sent
    assert v2["tasks"] == plan["tasks"][1:]

    at = client.get(CLOCK).json()["now"]
    event = {
        "event_id": "ev_scene", "household_id": "h_042", "source": "hub",
        "type": "package.brought_in", "at": at, "payload": {"removed_count": 1},
    }
    received = client.post("/v1/hub/events", json=[event]).json()
    assert received["accepted"] == ["ev_scene"]
    v3 = client.get(PLANS).json()["plans"][0]
    check_schema(v3, {"$ref": "plan.json"})
    assert v3["plan_version"] == 3
    assert v3["tasks"][0:3] == v2["tasks"][0:3]
    assert all(task["trigger"]["at"] == at for task in v3["tasks"][3:])


def test_scene_controls_are_off_by_default_and_authenticated_when_enabled():
    body = {"episode_id": "ep_9031"}
    assert TestClient(create_app()).post(SELECT, json=body).status_code == 404
    assert TestClient(create_app()).post(CALENDAR).status_code == 404
    client = TestClient(create_app(scene_controls=True))
    assert client.post(SELECT, json=body).status_code == 401
    assert client.post(CALENDAR).status_code == 401
    assert client.get(ACKS).status_code == 401


@pytest.mark.parametrize("live", [False, True])
def test_groceries_release_both_notices_on_an_eligible_package(live):
    http = TestClient(create_app("ep_9150", scene_controls=live, demo_mode=live), headers=HEADERS)
    client = ContractClient(http, "ep_9150", set())
    if live:
        assert http.post(SELECT, json={"episode_id": "ep_9150"}).status_code == 202
        assert upload(http, "groceries").status_code == 202
        finish_judgment(http)

    waiting = client.pull()["plans"][0]
    assert all(task["trigger"]["released"] is False for task in waiting["tasks"])
    at = datetime.fromisoformat(waiting["sent_at"]) + timedelta(seconds=1)
    event = {
        "event_id": "ev_grocery_package", "household_id": "h_042", "source": "hub",
        "type": "package.brought_in", "at": at.isoformat(), "payload": {"count": 1},
    }
    request = client.request
    first = request("POST", "/v1/hub/events", json=[event])
    assert first == {"accepted": [event["event_id"]], "plans_changed": True, "rejected": []}
    released = client.pull()["plans"][0]
    assert released["plan_version"] == waiting["plan_version"] + 1
    assert [task["task_id"] for task in released["tasks"]] == ["t_fridge#1", "t_fridge#2"]
    assert [task["actions"] for task in released["tasks"]] == [task["actions"] for task in waiting["tasks"]]
    assert all(task["trigger"] == {"event": event["type"], "released": True, "at": event["at"]}
               for task in released["tasks"])
    assert request("POST", "/v1/hub/events", json=[event])["plans_changed"] is False
    assert request("POST", "/v1/hub/events", json=[dict(event, event_id="ev_another_package")])["plans_changed"] is False
    assert client.pull()["plans"] == [released]

    for task in released["tasks"]:
        action = task["actions"][0]
        result = {
            "result_id": f"rs_notice_{task['task_id'][-1]}", "kind": "run",
            "operation_id": f"op_notice_{task['task_id'][-1]}", "plan_id": released["plan_id"],
            "plan_version": released["plan_version"], "task_id": task["task_id"],
            "device": action["device"], "cmd": action["cmd"], "substrate": "virtual",
            "status": "completed", "reason": None, "at": (at + timedelta(seconds=1)).isoformat(),
            "observed": {"notice": action["value"]},
        }
        assert request("POST", "/v1/hub/executions", json=result) == {"duplicate": False}
    episode = request("GET", EPISODE)
    assert episode["status"] == "judged"
    assert [task["state"] for task in episode["item_tasks"]] == ["done", "done"]
    assert client.cards()["cards"] == []


@pytest.mark.parametrize("newer_notices_released", [True, False])
def test_package_skips_newer_episode_without_live_waiting_tasks(newer_notices_released):
    """New uploads take priority even when their recorded share times move backwards."""
    http = TestClient(create_app(scene_controls=True, demo_mode=True), headers=HEADERS)
    client = ContractClient(http, "ep_9150", set())
    assert http.post(SELECT, json={"episode_id": "ep_9150"}).status_code == 202
    assert upload(http, "groceries").status_code == 202
    finish_judgment(http)
    older = client.pull()["plans"][0]
    assert all(task["trigger"]["released"] is False for task in older["tasks"])
    assert http.post(SELECT, json={"episode_id": "ep_9031"}).status_code == 202
    assert upload(http, "birthday").status_code == 202
    finish_judgment(http)
    newer = client.pull()["plans"][0]
    at = datetime.fromisoformat(newer["sent_at"]) + timedelta(seconds=1)
    event = {
        "event_id": "ev_package", "household_id": client.household, "source": "hub",
        "type": "package.brought_in", "at": at.isoformat(), "payload": {"count": 1},
    }
    route = "/v1/hub/events"
    if newer_notices_released:
        # The first package goes to the newest eligible episode.
        assert client.request("POST", route, json=[dict(event, event_id="ev_newer")])["plans_changed"]
        plans = client.pull()["plans"]
        assert len(plans) == 1 and plans[0]["plan_id"] == newer["plan_id"]
        newer = plans[0]
        assert all(task["trigger"]["released"] for task in newer["tasks"] if task["source"] == "item")
        event["at"] = (at + timedelta(seconds=1)).isoformat()
    else:
        # A rejected notice is dropped under §12.2 even if its published trigger is still waiting.
        client.request("POST", "/v1/hub/plans/{plan_id}/ack", 204, path={"plan_id": newer["plan_id"]}, json={
            "plan_version": newer["plan_version"], "status": "admitted", "rejected_tasks": [
                {"task_id": task["task_id"], "reason": "unsupported_cmd"}
                for task in newer["tasks"] if task["source"] == "item"
            ],
        })

    assert client.request("POST", route, json=[event]) == {
        "accepted": [event["event_id"]], "plans_changed": True, "rejected": [],
    }
    current, released = client.pull()["plans"]
    assert current == newer
    assert released["plan_id"] == older["plan_id"]
    assert released["plan_version"] == older["plan_version"] + 1
    trigger = {"event": event["type"], "released": True, "at": event["at"]}
    assert released["tasks"] == [dict(task, trigger=trigger) for task in older["tasks"]]
    assert client.request("POST", route, json=[event])["plans_changed"] is False
    assert client.request("POST", route, json=[dict(event, event_id="ev_no_waiting")])["plans_changed"] is False
    assert client.pull()["plans"] == [newer, released]


@pytest.mark.parametrize("via_app", [False, True])
def test_family_calendar_finds_time_from_the_calendar_request(via_app):
    http = TestClient(create_app("ep_9120", scene_controls=True, demo_mode=True), headers=HEADERS)
    client = ContractClient(http, "ep_9120", set())
    assert http.post(CALENDAR).status_code == 404
    assert http.post(SELECT, json={"episode_id": "ep_9031"}).status_code == 422
    assert http.post(SELECT, json={
        "episode_id": "ep_9120",
    }).json() == {"episode_id": "ep_9120", "household_id": "h_051"}
    assert upload(http, "family", "h_051").status_code == 202
    finish_judgment(http)
    assert client.request("GET", EPISODE)["status"] == "held"
    held = client.cards()
    assert held["cards"][0]["starts_at"] is None
    assert all(line["state"] == "held" and line["when"] is None for line in held["cards"][0]["lines"])
    waiting = client.pull()["plans"][0]
    assert [task["task_id"] for task in waiting["tasks"]] == ["t_fridge#3"]

    if via_app:
        # Finding a time must preserve an item release that happened while held.
        event = {
            "event_id": "ev_family_package", "household_id": "h_051", "source": "hub",
            "type": "package.brought_in", "at": http.get(CLOCK).json()["now"],
            "payload": {"count": 1},
        }
        assert client.request("POST", "/v1/hub/events", json=[event])["plans_changed"]
    before_calendar = client.pull()["plans"][0]

    def request():
        if via_app:
            return http.put("/v1/households/h_051/calendar", json=client.fixture("calendar.json"))
        return http.post(CALENDAR)

    before = datetime.fromisoformat(http.get(CLOCK).json()["now"])
    result = request()
    after = datetime.fromisoformat(http.get(CLOCK).json()["now"])
    assert result.status_code == 202 and result.json() == {"accepted": 1}

    found = client.cards(since=held["server_time"])["cards"][0]
    plan = client.pull()["plans"][0]
    assert plan["plan_version"] == before_calendar["plan_version"] + 1
    assert plan["household_id"] == "h_051"
    assert found["card_id"] == held["cards"][0]["card_id"] and found["notify"] is True
    assert found["starts_at"] == client.fixture("card.found.json")["starts_at"]
    assert before <= datetime.fromisoformat(plan["sent_at"]) <= after
    clean, music, notice = plan["tasks"]
    assert [clean, music] == client.fixture("plan.v2.json")["tasks"][:2]
    assert notice == before_calendar["tasks"][0]
    assert client.request("GET", EPISODE)["status"] == "notified"
    assert request().status_code == 202
    assert client.pull()["plans"] == [plan]


def test_history_keeps_prior_episodes_rationale_and_cards_across_orders():
    http = TestClient(create_app(scene_controls=True, demo_mode=True), headers=HEADERS)
    history = "/v1/households/h_042/episodes"
    unseen = "2026-10-15T20:59:00+09:00"
    for episode_id, source in (("ep_9031", "birthday"), ("ep_9150", "groceries")):
        assert http.post(SELECT, json={"episode_id": episode_id}).status_code == 202
        assert upload(http, source).json()["episode_id"] == episode_id
        finish_judgment(http)

    first_page = http.get(history, params={"limit": 1}).json()
    assert [episode["episode_id"] for episode in first_page["episodes"]] == ["ep_9150"]
    second_page = http.get(history, params={"before": first_page["next_before"]}).json()
    assert [episode["episode_id"] for episode in second_page["episodes"]] == ["ep_9031"]
    old = http.get("/v1/episodes/ep_9031").json()
    assert old["card_ids"] == ["nc_331"]
    assert http.get("/v1/episodes/ep_9031/rationale").json()["episode_id"] == "ep_9031"
    assert [card["card_id"] for card in http.get(CARDS, params={"since": unseen}).json()["cards"]] == ["nc_331"]
    assert [plan["plan_id"] for plan in http.get(PLANS).json()["plans"]] == ["ep_9150"]

    # A new source can reuse the same template without replacing its earlier episode.
    assert http.post(SELECT, json={"episode_id": "ep_9031"}).status_code == 202
    later = upload(http, "other-birthday").json()["episode_id"]
    assert later != "ep_9031"
    finish_judgment(http)
    assert upload(http, "birthday").json()["episode_id"] == "ep_9031"
    assert http.get("/v1/episodes/ep_9031").json() == old
    assert len({card["card_id"] for card in http.get(CARDS).json()["cards"]}) == 2
    assert [plan["plan_id"] for plan in http.get(PLANS).json()["plans"]] == [later]
