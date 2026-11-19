"""HTTP checks for opt-in, wall-clock scene replay."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from . import create_app
from .test_fixture_server import HEADERS, check_schema

SELECT = "/_fixture/scene/next-order"
ACKS = "/_fixture/scene/acks"
PLANS = "/v1/hub/plans?household=h_042"
CARDS = "/v1/households/h_042/cards"


def upload(client, source, household="h_042"):
    return client.post(
        "/v1/orders",
        data={"household_id": household, "source_id": source},
        files={"images": ("capture.png", b"fixture upload", "image/png")},
    )


def test_scene_selection_publishes_on_the_next_valid_new_order():
    client = TestClient(create_app(scene_controls=True, demo_mode=True), headers=HEADERS)
    assert client.get(CARDS).json()["cards"] == []
    assert client.get(PLANS).json()["plans"] == []
    assert client.post(SELECT, json={"episode_id": "ep_9120"}).status_code == 422
    assert client.post(SELECT, json={"episode_id": "ep_9031", "duration_seconds": 0}).status_code == 422
    assert client.post(SELECT, json={"episode_id": "ep_9031"}).status_code == 202
    assert client.get(CARDS).json()["cards"] == []
    assert upload(client, "wrong-home", "h_051").status_code == 404
    result = upload(client, "birthday")
    assert result.status_code == 202
    assert result.json() == {"episode_id": "ep_9031", "status": "received"}
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
    assert client.get(CARDS).json()["cards"] == []
    assert client.get("/v1/episodes/ep_9150").json()["household_id"] == "h_042"
    assert client.get(PLANS).json()["plans"][0]["plan_id"] == "ep_9150"


def test_scene_demo_wall_times_and_live_revisions():
    client = TestClient(create_app(scene_controls=True, demo_mode=True), headers=HEADERS)
    choice = {"episode_id": "ep_9031", "starts_in_seconds": 190, "duration_seconds": 40}
    assert client.post(SELECT, json=choice).status_code == 202
    before = datetime.now(timezone.utc)
    assert upload(client, "birthday").status_code == 202
    after = datetime.now(timezone.utc)

    plan = client.get(PLANS).json()["plans"][0]
    check_schema(plan, {"$ref": "plan.json"})
    card = client.get(CARDS).json()["cards"][0]
    check_schema(card, {"$ref": "card.json"})
    sent = datetime.fromisoformat(plan["sent_at"])
    assert before <= sent <= after
    starts = datetime.fromisoformat(card["starts_at"])
    assert starts == sent + timedelta(seconds=190)
    tasks = {task["task_id"]: task for task in plan["tasks"]}
    assert datetime.fromisoformat(tasks["t_clean#1"]["trigger"]["time"]) == starts - timedelta(minutes=3)
    mood = tasks["t_mood#3"]
    assert datetime.fromisoformat(mood["trigger"]["window"]["from"]) == starts - timedelta(minutes=1)
    ends = datetime.fromisoformat(mood["trigger"]["window"]["to"])
    assert ends == starts + timedelta(seconds=40)
    assert datetime.fromisoformat(mood["end"]["or_time"]) == ends + timedelta(minutes=10)
    assert tasks["t_safe#2"]["end"]["or_time"] == mood["end"]["or_time"]
    assert tasks["t_fridge#5"]["end"]["after"] == "2m"
    assert [line["when"] for line in card["lines"][:2]] == [
        tasks["t_clean#1"]["trigger"], tasks["t_safe#2"]["trigger"]
    ]

    reaction = {"reaction": "line_off", "task_id": "t_clean#1"}
    assert client.post(f"/v1/cards/{card['card_id']}/reactions", json=reaction).status_code == 200
    v2 = client.get(PLANS).json()["plans"][0]
    assert v2["plan_version"] == 2
    assert datetime.fromisoformat(v2["sent_at"]) > sent
    assert v2["tasks"] == plan["tasks"][1:]

    at = datetime.now(timezone.utc).isoformat()
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
    client = TestClient(create_app(scene_controls=True))
    assert client.post(SELECT, json=body).status_code == 401
    assert client.get(ACKS).status_code == 401
