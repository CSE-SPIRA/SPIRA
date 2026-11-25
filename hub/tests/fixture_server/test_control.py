from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from . import create_app
from .api import CONTROL
from .catalogue import CASES_BY_ID, STAGE_NAMES
from .control_transport import ConnectionDropped
from .replay import FIXTURES, read_json
from .scene_support import NextOrder, server_numbers
from .story_clock import StoryClock
from .test_fixture_server import HEADERS, check_schema
from .test_scene_support import CARDS, CLOCK, PLANS, SELECT, upload

BASE_URL = "http://127.0.0.1"
AUTH = {"Authorization": HEADERS["Authorization"]}
HUB = {"X-API-Key": HEADERS["X-API-Key"]}
EPISODE = "/v1/episodes/ep_9031"
MEMORY = "/v1/households/h_042/memory"
REACTIONS = "/v1/cards/nc_331/reactions"
PAUSE = "/v1/households/h_042/pause"
SHARE = "2026-10-15T21:00:08+09:00"
EVENTS = "/v1/hub/events"
EXECUTIONS = "/v1/hub/executions"


def app_client(episode="ep_9031"):
    return TestClient(create_app(episode, scene_controls=True, default_scene=NextOrder(episode_id=episode)),
                      base_url=BASE_URL, client=("127.0.0.1", 10101), headers=AUTH)


@pytest.fixture
def client():
    with app_client() as http:
        yield http


def body(response, status=200, schema=None):
    assert response.status_code == status, response.text
    if status == 204:
        assert response.content == b""
        return None
    payload = response.json()
    if schema:
        check_schema(payload, {"$ref": f"{schema}.json"})
    return payload


def error(response, status, code):
    payload = body(response, status, "error")
    assert payload["code"] == code
    return payload


def action(client, endpoint, **payload):
    return body(client.post(f"{CONTROL}/{endpoint}", json=payload))


def state(client):
    return body(client.get(f"{CONTROL}/state"))


def arm(client, case):
    return action(client, "case", id=case)


def accept(client, source="rehearsal", household="h_042"):
    return body(upload(client, source, household), 202, "order_accepted")


def jump(client, at):
    return action(client, "clock", action="set", at=at)


def stages(snapshot):
    return {stage["id"]: stage for stage in snapshot["timeline"]}


def publish(client):
    return jump(client, stages(state(client))["published"]["at"])


def pull(client, household="h_042"):
    return body(client.get(f"/v1/hub/plans?household={household}", headers=HUB), 200, "plan_pull")


def recorded(file, episode="ep_9031"):
    return read_json(FIXTURES / episode / f"{file}.json")


def test_control_routes_loopback_and_html(client):
    page = client.get(CONTROL)
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "예시 판단, 추론 아님" in page.text
    for label in ("지금", "시계", "판단 속도", "회차", "경우", "고장", "요청 기록"):
        assert label in page.text
    assert "<script src=" not in page.text
    assert state(client)["episode"] is None
    assert error(client.get(CONTROL, headers={"Host": "remote.test"}), 403, "forbidden")
    assert error(client.post(CONTROL + "/case", headers={"Origin": "https://remote.test"},
                             json={"id": "slow"}), 403, "forbidden")
    with TestClient(create_app(scene_controls=True), base_url=BASE_URL, client=("192.0.2.1", 1)) as remote:
        assert error(remote.get(CONTROL + "/state"), 403, "forbidden")
    assert client.get(CONTROL + "/state").headers["cache-control"] == "no-store"
    assert TestClient(create_app()).get(CONTROL).status_code == 404


def test_off_matches_original_scene():
    # Keep one fixture completely untouched while reading the other's control state.
    with app_client() as observed, app_client() as original:
        info = state(observed)
        assert not (info["faults"] or info["active_case"] or info["queued_next_order"] or info["next_pace"])
        for client in (observed, original):
            assert accept(client) == {"episode_id": "ep_9031", "status": "received"}
            result = client.post(CLOCK, json={"set_to": "2026-10-15T21:11:08+09:00"})
            assert result.status_code == 200
        state(observed)
        assert pull(observed) == pull(original)
        assert body(observed.get(CARDS), schema="cards_response")["cards"] == body(
            original.get(CARDS), schema="cards_response")["cards"]
        assert body(observed.get(EPISODE), schema="episode") == body(original.get(EPISODE), schema="episode")


def test_clock_actions_and_countdown(client):
    jump(client, SHARE)
    paused = action(client, "clock", action="pause")["clock"]
    assert paused["paused"] and paused["rate"] == 0
    assert state(client)["clock"]["now"] == paused["now"]
    assert client.get(CLOCK).json()["rate"] > 0  # Existing Hub reader.
    assert action(client, "clock", action="resume")["clock"]["rate"] == 1
    assert action(client, "clock", action="rate", rate=30)["clock"]["rate"] == 30
    action(client, "clock", action="pause")
    assert action(client, "clock", action="resume")["clock"]["rate"] == 30
    accept(client)
    stopped = action(client, "clock", action="pause")
    assert stopped["seconds_until_next_stage"] is None
    resumed = action(client, "clock", action="rate", rate=4)
    assert 0 < resumed["seconds_until_next_stage"] <= .25
    moment = resumed["moments"][0]
    ramp = action(client, "clock", action="advance", moment=moment["id"], over_seconds=10)["clock"]
    assert ramp["ramp_active"] and ramp["rate"] > 1
    error(client.post(f"{CONTROL}/clock", json={"action": "advance", "at": SHARE}), 409, "invalid_request")
    jump(client, SHARE)
    assert action(client, "clock", action="next")["clock"]["ramp_active"]
    jump(client, SHARE)
    assert action(client, "clock", action="advance", at="2026-10-15T22:00:08+09:00")["clock"]["ramp_active"]


def test_clock_countdown_accounts_for_ramp_ending():
    start = datetime.fromisoformat(SHARE)
    clock = StoryClock(start)
    clock.advance(start + timedelta(seconds=60), start, 6)
    three_seconds_later = start + timedelta(seconds=3)
    assert clock.seconds_until(start + timedelta(seconds=50), three_seconds_later) == 2
    assert clock.seconds_until(start + timedelta(seconds=65), three_seconds_later) == 8
    clock.pause(three_seconds_later)
    assert clock.seconds_until(start + timedelta(seconds=65), three_seconds_later) is None
    clock.resume(three_seconds_later)
    assert clock.rate_at(three_seconds_later) == 1


def test_episode_actions_preserve_devices_and_allocate_fresh_ids(client):
    allowed = state(client)["available_episodes"]
    assert allowed == ["ep_9031", "ep_9150"]
    unknown = client.post(f"{CONTROL}/episode", json={"action": "select", "episode_id": "ep_9120"})
    error(unknown, 422, "validation_error")
    selected = action(client, "episode", action="select", episode_id="ep_9150")
    assert selected["queued_next_order"] == "ep_9150"
    shared = action(client, "episode", action="share")
    assert shared["sample_response"] == {"status": 202, "body": {"episode_id": "ep_9150", "status": "received"}}
    check_schema(shared["sample_response"]["body"], {"$ref": "order_accepted.json"})
    publication = publish(client)
    before = pull(client)
    assert before["plans"][0]["plan_id"] == "ep_9150"
    reset = action(client, "episode", action="reset")
    assert reset["episode"] is None and reset["timeline"] == [] and reset["cards"] == [] and reset["plans"] == []
    expected = datetime.fromisoformat(publication["episode"]["shared_at"]) - timedelta(minutes=1)
    assert datetime.fromisoformat(reset["clock"]["story_at"]) == expected
    assert pull(client)["devices_revision"] == before["devices_revision"]
    assert pull(client)["plans"] == []
    assert action(client, "episode", action="share")["episode"]["id"] == "ep_91502"


@pytest.mark.parametrize("case", ["invalid-image", "duplicate-share", "order-edit", "stale-edit"])
def test_order_responses(client, case):
    armed = arm(client, case)
    assert armed["active_case"] == case
    if case == "invalid-image":
        error(upload(client, "refused"), 400, "invalid_image")
        invalid = client.post("/v1/orders", data={"household_id": "h_042"},
                              files={"images": ("file.txt", b"file", "text/plain")})
        error(invalid, 400, "invalid_image")
        assert state(client)["episode"] is None
        assert accept(client) == {"episode_id": "ep_9031", "status": "received"}
        return
    shared = action(client, "episode", action="share")
    if case == "duplicate-share":
        repeat = action(client, "episode", action="repeat")["sample_response"]
        assert repeat == {"status": 200, "body": shared["sample_response"]["body"]}
        check_schema(repeat["body"], {"$ref": "order_accepted.json"})
        assert body(client.get("/v1/households/h_042/episodes"), schema="episode_list")["episodes"][0]["episode_id"] == "ep_9031"
        return
    publish(client)
    items = [{key: item[key] for key in ("item_id", "name", "qty")} for item in recorded("episode")["items"]]
    response = client.put(EPISODE + "/order", json={"items": items})
    if case == "stale-edit":
        error(response, 409, "stale_revision")
        response = client.put(EPISODE + "/order", json={"items": items})
    assert body(response, 202, "order_accepted") == {"episode_id": "ep_9031", "status": "received"}


def test_read_failed(client):
    arm(client, "read-failed")
    accepted = accept(client)
    assert accepted["status"] == "received"
    snapshot = state(client)
    jump(client, stages(snapshot)["items"]["at"])
    episode = body(client.get(EPISODE), schema="episode")
    assert (episode["status"], episode["items"], episode["card_ids"], episode["item_tasks"]) == ("read_failed", [], [], [])
    assert pull(client)["plans"] == []
    assert body(client.get(CARDS), schema="cards_response")["cards"] == []
    error(client.get(EPISODE + "/rationale"), 404, "not_found")
    assert state(client)["next_stage"] is None


def test_second_capture(client):
    arm(client, "second-capture")
    shared = action(client, "episode", action="share")
    at = datetime.fromisoformat(shared["episode"]["shared_at"]) + timedelta(seconds=64)
    jump(client, at.isoformat())
    capture = action(client, "episode", action="capture")
    assert capture["sample_response"] == {"status": 202, "body": {"episode_id": "ep_9031", "status": "received"}}
    check_schema(capture["sample_response"]["body"], {"$ref": "order_accepted.json"})
    assert stages(capture)["quiet_window"]["at"] > stages(shared)["quiet_window"]["at"]
    assert not capture["can_capture"]
    jump(client, stages(shared)["published"]["at"])
    assert pull(client)["plans"] == []
    publish(client)
    assert len(pull(client)["plans"]) == 1
    episodes = body(client.get("/v1/households/h_042/episodes"), schema="episode_list")
    assert len(episodes["episodes"]) == 1


@pytest.mark.parametrize("case", ["birthday", "groceries", "held", "calendar"])
def test_recorded_results(case):
    household, id_ = ("h_051", "ep_9120") if case in ("held", "calendar") else ("h_042", "ep_9031")
    with app_client(id_) as client:
        arm(client, "held" if case == "calendar" else case)
        accepted = accept(client, household=household)
        id_ = accepted["episode_id"]
        if household == "h_051":
            assert id_ == "ep_9120"
        publish(client)
        episode = body(client.get(f"/v1/episodes/{id_}"), schema="episode")
        cards_url = f"/v1/households/{household}/cards"
        cards = body(client.get(cards_url), schema="cards_response")["cards"]
        plan, = pull(client, household=household)["plans"]
        assert plan["tasks"] == recorded("plan.v1", id_)["tasks"]
        if case == "groceries":
            assert id_ == "ep_9150" and episode["card_ids"] == [] and not cards
            rationale = body(client.get(f"/v1/episodes/{id_}/rationale"), schema="rationale")
            assert rationale["none_reason"] == recorded("rationale", id_)["none_reason"]
            assert rationale["intents"] == []
        elif case == "birthday":
            assert id_ == "ep_9031" and cards[0]["text"] == recorded("card.v1")["text"]
            assert episode["status"] == "notified"
        else:
            assert episode["status"] == "held" and cards[0]["starts_at"] is None
            if case == "calendar":
                calendar = arm(client, case)
                assert calendar["sample_response"]["status"] == 202
                check_schema(calendar["sample_response"]["body"], {"$ref": "calendar_response.json"})
                card, = body(client.get(cards_url), schema="cards_response")["cards"]
                assert card["starts_at"] == recorded("card.found", id_)["starts_at"] and card["notify"]
                assert pull(client, household=household)["plans"][0]["plan_version"] == plan["plan_version"] + 1


@pytest.mark.parametrize("preset,quiet", [("server", None), ("fast", 12), ("slow", None)],
                         ids=["server", "fast", "slow"])
def test_paces(client, preset, quiet):
    queued = arm(client, "server-pace" if preset == "server" else preset)
    assert queued["next_pace"]["preset"] == preset
    accept(client)
    snapshot = state(client)
    quiet_at = datetime.fromisoformat(stages(snapshot)["quiet_window"]["at"])
    first = datetime.fromisoformat(snapshot["episode"]["shared_at"])
    expected = quiet or server_numbers()["quiet_s"] * (4 if preset == "slow" else 1)
    assert quiet_at - first == timedelta(seconds=expected)
    assert snapshot["next_pace"] is None and pull(client)["plans"] == []
    halfway = jump(client, stages(snapshot)["items"]["at"])
    changed = action(client, "judgment", preset="custom", scope="current", quiet_seconds=80,
                     offsets={"reading": 1, "items": 7, "evidence": 1, "intents": 2, "tasks": 3, "published": 4})
    assert stages(changed)["items"] == stages(halfway)["items"]
    assert datetime.fromisoformat(stages(changed)["quiet_window"]["at"]) - first == timedelta(seconds=80)
    done = publish(client)
    assert all(step["done"] for step in done["timeline"])
    assert pull(client)["plans"][0]["sent_at"] == stages(done)["published"]["at"]


@pytest.mark.parametrize("stage", STAGE_NAMES)
def test_stuck_and_release(client, stage):
    arm(client, f"stuck-{stage}")
    accept(client)
    held = publish(client)
    before = "reading" if stage == "received" else stage
    assert stages(held)[before]["held"] and held["seconds_until_next_stage"] is None
    assert pull(client)["plans"] == []
    assert body(client.get(CARDS), schema="cards_response")["cards"] == []
    assert body(client.get(EPISODE), schema="episode")["status"] in ("received", "reading", "judged")
    released = arm(client, "release-now")
    assert all(step["done"] for step in released["timeline"])
    assert len(pull(client)["plans"]) == 1
    assert body(client.get(CARDS), schema="cards_response")["cards"][0]["card_id"] == "nc_331"


def test_partial_rationale(client):
    arm(client, "partial-rationale")
    accept(client)
    jump(client, stages(state(client))["evidence"]["at"])
    rationale = body(client.get(EPISODE + "/rationale"), schema="rationale")
    assert rationale["evidence"] == recorded("rationale")["evidence"]
    assert rationale["intents"] == rationale["tasks"] == [] and rationale["none_reason"] is None
    assert pull(client)["plans"] == []
    finished = action(client, "judgment", preset="release", scope="current")
    assert finished["cards"][0]["episode_id"] == "ep_9031"
    assert body(client.get(EPISODE + "/rationale"), schema="rationale")["intents"] == recorded("rationale")["intents"]


def test_cannot_retime_a_stage_already_passed(client):
    accept(client)
    jump(client, stages(state(client))["items"]["at"])
    error(client.post(f"{CONTROL}/case", json={"id": "stuck-reading"}), 409, "invalid_request")
    error(client.post(f"{CONTROL}/judgment", json={"preset": "custom", "quiet_seconds": 0}), 409, "invalid_request")
    error(client.post(f"{CONTROL}/case", json={"id": "edit-rejudge"}), 409, "invalid_request")
    error(client.post(f"{CONTROL}/case", json={"id": "missing"}), 404, "not_found")
    assert arm(client, None)["active_case"] is None


@pytest.mark.parametrize("case", ["package", "event-resend"])
def test_package_and_event_resend(client, case):
    accept(client)
    publish(client)
    plans = pull(client)["plans"]
    package = recorded("events")[0]
    arm(client, case)
    response = client.post(EVENTS, json=[package], headers=HUB)
    if case == "event-resend":
        error(response, 503, "internal")
    else:
        assert body(response, schema="event_response") == {
            "plans_changed": True, "accepted": [package["event_id"]], "rejected": [],
        }
    released = pull(client)["plans"][0]
    assert released["plan_version"] == plans[0]["plan_version"] + 1
    assert all(task["trigger"]["released"] for task in released["tasks"] if task["source"] == "item")
    reply = body(client.post(EVENTS, json=[package], headers=HUB), schema="event_response")
    assert reply == {"plans_changed": False, "accepted": [package["event_id"]], "rejected": []}
    assert pull(client)["plans"] == [released]


def test_execution_resend(client):
    accept(client)
    publish(client)
    arm(client, "result-resend")
    result = recorded("executions")[6]
    error(client.post(EXECUTIONS, json=result, headers=HUB), 503, "internal")
    assert body(client.post(EXECUTIONS, json=result, headers=HUB), schema="execution_response") == {"duplicate": True}
    log = body(client.get(f"{CONTROL}/log"))["requests"]
    assert [row["status"] for row in log if row["path"] == EXECUTIONS] == [200, 503]


def test_apply_then_fail_app_share_repeats_same_source(client):
    action(client, "fault", group="app", kind="apply_then_fail", route="order", count=1)
    failed = action(client, "episode", action="share")
    assert failed["sample_response"]["status"] == 503
    check_schema(failed["sample_response"]["body"], {"$ref": "error.json"})
    assert failed["can_repeat"] and failed["episode"]["id"] == "ep_9031"
    repeated = action(client, "episode", action="repeat")
    assert repeated["sample_response"] == {"status": 200, "body": {"episode_id": "ep_9031", "status": "received"}}
    assert not repeated["faults"]


def test_sample_share_surfaces_connection_drop(client):
    arm(client, "app-drop")
    dropped = action(client, "episode", action="share")
    assert dropped["sample_response"] == {"status": None, "body": None}
    assert dropped["episode"] is None and not dropped["can_repeat"]


@pytest.mark.parametrize("case", ["line-off-before", "line-off-after", "line-on-after"])
def test_line_reactions(client, case):
    accept(client)
    publish(client)
    arm(client, case)
    result = next(r for r in recorded("executions") if r["task_id"] == "t_oven#4")
    started = case != "line-off-before"
    if started:
        jump(client, result["at"])
        assert body(client.post(EXECUTIONS, json=dict(result, plan_version=1), headers=HUB),
                    schema="execution_response") == {"duplicate": False}
    line_off = {"reaction": "line_off", "task_id": "t_oven#4"}
    card = body(client.post(REACTIONS, json=line_off), schema="card")
    assert next(line for line in card["lines"] if line["task_id"] == "t_oven#4")["state"] == "off"
    plan, = pull(client)["plans"]
    assert plan["plan_version"] == 2
    assert {"task_id": "t_oven#4", "restore": started} in plan["cancelled"]
    if case == "line-on-after":
        error(client.post(REACTIONS, json=dict(line_off, reaction="line_on")), 409, "line_started")
        assert pull(client)["plans"] == [plan]


def test_stop_ignores_reactions(client):
    accept(client)
    publish(client)
    arm(client, "stop")
    stopped = body(client.post(REACTIONS, json={"reaction": "stop"}), schema="card")
    assert stopped["stopped"]
    ignored = body(client.post(REACTIONS, json={"reaction": "line_on", "task_id": "t_clean#1"}), schema="card")
    assert stopped == ignored
    plan, = pull(client)["plans"]
    assert plan["plan_version"] == 2
    assert {task["source"] for task in plan["tasks"]} == {"item"}


def test_pause_and_paused_share(client):
    accept(client)
    publish(client)
    arm(client, "pause-resume")
    assert body(client.post(PAUSE, json={"paused": True}), schema="pause")["paused"]
    plan, = pull(client)["plans"]
    assert plan["plan_version"] == 2 and not plan["tasks"]
    assert len(plan["cancelled"]) == 6
    assert not body(client.post(PAUSE, json={"paused": False}), schema="pause")["paused"]
    arm(client, "paused-share")
    skipped = accept(client, "while-paused")
    assert skipped["status"] == "paused_skip"
    detail = body(client.get(f"/v1/episodes/{skipped['episode_id']}"), schema="episode")
    assert detail["status"] == "paused_skip" and detail["items"] == []
    assert pull(client)["paused"] and pull(client)["plans"] == [plan]
    assert not action(client, "episode", action="resume")["household"]["paused"]
    assert accept(client, "after-paused")["status"] == "received"


def test_memory_delete(client):
    accept(client)
    publish(client)
    arm(client, "memory-delete")
    fallback = next(task["end"]["or_time"] for task in pull(client)["plans"][0]["tasks"] if task["task_id"] == "t_safe#2")
    jump(client, fallback)
    memory = body(client.get(MEMORY), schema="memory")
    case = memory["intents"][0]["episodes"][0]["case_id"]
    assert body(client.delete(f"{MEMORY}/{case}"), 204) is None
    assert body(client.get(MEMORY), schema="memory") == {"household_id": "h_042", "intents": []}


@pytest.mark.parametrize("case", [
    "latency", "internal", "app-unavailable", "hub-unavailable", "app-drop", "hub-drop",
    "app-unauthorized", "forbidden", "not-found", "health", "no-clock",
])
def test_availability(client, case):
    arm(client, case)
    spec = CASES_BY_ID[case].action["fault"]
    group = spec["group"]
    path = {"app": CARDS, "hub": PLANS, "clock": CLOCK, "health": "/health"}[group]
    if spec["kind"] == "drop":
        with pytest.raises(ConnectionDropped):
            client.get(path, headers=HUB if group == "hub" else AUTH)
    else:
        response = client.get(path, headers=HUB if group == "hub" else AUTH)
        if case == "health":
            assert body(response, 503, "health") == {"status": "degraded"}
        elif case == "latency":
            body(response, schema="cards_response")
            elapsed = state(client)["last"]["app_card_poll"]["latency_ms"]
            assert elapsed >= spec["delay_ms"]
        else:
            code = {"internal": "internal", "app-unauthorized": "unauthorized",
                    "app-unavailable": "internal", "hub-unavailable": "internal",
                    "forbidden": "forbidden", "not-found": "not_found", "no-clock": "not_found"}[case]
            error(response, spec["status"], code)
    if group in ("clock", "health"):
        assert state(client)["faults"][0]["count"] is None
        assert not action(client, f"fault/{group}/clear")["faults"]
    assert client.get(path, headers=HUB if group == "hub" else AUTH).status_code == 200


def test_fault_counts_and_until_cleared(client):
    action(client, "fault", group="app", kind="status", status=403, count=2)
    assert pull(client)["plans"] == []
    assert state(client)["faults"][0]["count"] == 2
    for _ in range(2):
        error(client.get(CARDS), 403, "forbidden")
    assert state(client)["faults"] == []
    body(client.get(CARDS), schema="cards_response")
    action(client, "fault", group="hub", kind="status", status=503, count=None)
    for _ in range(3):
        error(client.get(PLANS, headers=HUB), 503, "internal")
    assert state(client)["faults"][0]["count"] is None
    action(client, "fault/hub/clear")
    assert pull(client)["plans"] == []
    assert client.post(f"{CONTROL}/fault", json={"group": "health", "kind": "status", "status": 500}).status_code == 422


def test_traffic_and_per_version_receipts(client):
    accept(client)
    publish(client)
    plan, = pull(client)["plans"]
    ack = recorded("ack.v1")
    body(client.post(f"/v1/hub/plans/{plan['plan_id']}/ack", json=ack, headers=HUB), 204)
    client.get(CARDS)
    client.get(CLOCK, headers={"X-SPIRA-Demo-Client": "shell"})
    snap = state(client)
    assert snap["last"]["hub_pull"]["client"] == "hub"
    assert snap["last"]["app_card_poll"]["client"] == "app"
    assert snap["last"]["shell_request"]["surface"] == "shell"
    receipt, = snap["plans"]
    assert receipt["ack"] == ack and receipt["acked_at"] and receipt["pulled_at"]
    assert all(task["status"] == "accepted" for task in receipt["tasks"])
    for _ in range(305):
        client.get("/health", params={"ignore": "fixture-query-marker"})
    log = body(client.get(f"{CONTROL}/log"))
    assert len(log["requests"]) == 300
    assert log["requests"][0]["id"] == log["last_id"]
    assert log["requests"][0]["path"] == "/health"
    assert not any("fixture-query-marker" in str(row) for row in log["requests"])
    later = body(client.get(f"{CONTROL}/log", params={"after": log["last_id"]}))
    assert len(later["requests"]) == 1
    assert later["requests"][0]["client"] == "loopback-control"


def test_realistic_preset_jitters_and_bursts_and_injects_one_retryable_503(client):
    from .control_transport import Traffic

    page = client.get(CONTROL)
    assert page.status_code == 200 and "현실 지연" in page.text
    assert state(client)["realistic_seed"] is None
    assert action(client, "realistic", seed=7)["realistic_seed"] == 7
    accept(client)
    timeline = stages(state(client))
    assert datetime.fromisoformat(timeline["items"]["at"]) - datetime.fromisoformat(
        timeline["received"]["at"]
    ) == timedelta(seconds=13)
    assert timeline["tasks"]["at"] == timeline["published"]["at"]
    jump(client, timeline["intents"]["at"])
    path = f"{EPISODE}/rationale"
    assert [client.get(path).status_code for _ in range(6)] == [200, 200, 200, 503, 200, 200]
    requests = body(client.get(f"{CONTROL}/log"))["requests"]
    assert sum(row["fault"] is not None for row in requests if row["path"] == path) == 1
    assert action(client, "realistic", seed=None)["realistic_seed"] is None

    a, b = Traffic(), Traffic()
    for traffic in (a, b):
        traffic.set_realistic(7)
    delays = [a.realistic_reply("GET", path)[0] for _ in range(6)]
    assert delays == [b.realistic_reply("GET", path)[0] for _ in range(6)]
    assert len(set(delays)) > 1 and min(delays) >= 35 and max(delays) <= 420
    assert a.realistic_reply("GET", PLANS) == (0, None)
