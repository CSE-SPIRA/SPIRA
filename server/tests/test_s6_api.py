"""S6 minimal API (spec §12): households, profile, calendar PUT, cards poll, hub device list, plan pull, ack.
T22 (through the route) T31 T39 (routes) T40 T41 T50; device revisions; calendar tagging in the background."""

import copy

import pytest
from fastapi.testclient import TestClient
from spira_contracts.validate import validate
from sqlalchemy import select

from spira_server import clock
from spira_server.db.engine import session_scope
from spira_server.db.models import CalendarEvent, Card, CardLine, DeviceList, Episode, Household, Plan, Task
from spira_server.llm import prompts
from spira_server.main import create_app
from spira_server.pipeline import s5_plan
from spira_server.pipeline.s2_calendar import CalendarInput, user_message

from . import s5_helpers as h
from .factories import fixture, household, hub_key
from .s4_helpers import JUDGED, ep9031, output

ACKED = clock.parse("2026-10-15T21:11:55+09:00")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(start_background=False))


def _ep9031(mock_llm) -> str:
    ep = ep9031()
    h.restart_card_ids(331)
    s5_plan.finalize(ep, h.s4_for(mock_llm, ep, output(), JUDGED), now=JUDGED)
    return ep


def _episode(s, ep):
    return s.execute(select(Episode).where(Episode.id == ep).with_for_update()).scalar_one()


def _hub(key: str) -> dict:
    return {"X-API-Key": key}


# ------------------------------------------------------------------------------------- households and profile

def test_t39_t40_create_household_and_profile(client, app_headers):
    r = client.post("/v1/households", json=fixture("ep_9031/household.create.json"), headers=app_headers)
    assert r.status_code == 201
    validate(r.json(), "household_created.json")
    hid, key = r.json()["household_id"], r.json()["hub_api_key"]
    assert hid == "h_1" and key.startswith("hk_") and len(key) == 67
    with session_scope() as s:
        row = s.get(Household, hid)
        assert key not in row.hub_key_hash and len(row.hub_key_hash) == 64          # only the hash is stored
        assert row.household_types == ["3~4인", "부부·커플", "영유아 자녀", "맞벌이"]
    assert client.get("/v1/hub/plans", params={"household": hid}, headers=_hub(key)).status_code == 200

    assert client.post("/v1/households", json={"household_types": []}, headers=app_headers).status_code == 201
    for bad in (["1인", "부부·커플"], ["2인", "3~4인"], ["외계인"], ["맞벌이"]):
        r = client.post("/v1/households", json={"household_types": bad}, headers=app_headers)
        assert (r.status_code, r.json()["code"]) == (422, "household_types_invalid"), bad
        validate(r.json(), "error.json")
    r = client.post("/v1/households", json={"household_types": "2인"}, headers=app_headers)
    assert (r.status_code, r.json()["code"], r.json()["details"]["path"]) == (422, "validation_error",
                                                                               "household_types")

    rare = ["1인", "대학생", "재택근무"]
    r = client.put(f"/v1/households/{hid}/profile", json={"household_types": rare}, headers=app_headers)
    assert r.status_code == 200 and r.json() == {"household_id": hid, "household_types": rare}
    validate(r.json(), "profile.json")
    r = client.put(f"/v1/households/{hid}/profile", json={"household_types": ["1인", "부부·커플"]},
                   headers=app_headers)
    assert r.json()["code"] == "household_types_invalid"
    with session_scope() as s:
        assert s.get(Household, hid).household_types == rare                      # unchanged by the 422
    r = client.put("/v1/households/h_999/profile", json={"household_types": []}, headers=app_headers)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


# ------------------------------------------------------------------------------------------------ hub auth T41

def test_t41_hub_key_and_household(client, app_headers, mock_llm):
    ep = _ep9031(mock_llm)
    key = hub_key("h_042")
    household("h_077")
    other = hub_key("h_077")
    devices = fixture("ep_9031/devices.json")

    for headers in ({}, _hub("hk_" + "0" * 64)):
        r = client.put("/v1/hub/households/h_042/devices", json={"bad": 1}, headers=headers)
        assert (r.status_code, r.json()["code"]) == (401, "unauthorized")         # 401 before the bad body
        validate(r.json(), "error.json")
        assert client.get("/v1/hub/plans", params={"household": "h_042"}, headers=headers).status_code == 401
    forbidden = [
        client.put("/v1/hub/households/h_042/devices", json=devices, headers=_hub(other)),
        client.put("/v1/hub/households/h_077/devices", json=devices, headers=_hub(other)),   # body names h_042
        client.get("/v1/hub/plans", params={"household": "h_042"}, headers=_hub(other)),
        client.post(f"/v1/hub/plans/{ep}/ack", json=fixture("ep_9031/ack.v1.json"), headers=_hub(other)),
    ]
    for r in forbidden:
        assert (r.status_code, r.json()["code"]) == (403, "forbidden")
        validate(r.json(), "error.json")
    with session_scope() as s:
        assert s.get(DeviceList, "h_077") is None and s.get(Plan, (ep, 1)).ack is None   # nothing written
    assert client.get("/v1/hub/plans", params={"household": "h_042"}, headers=_hub(key)).status_code == 200
    assert client.get("/v1/hub/plans", params={"household": "h_042"}, headers=app_headers).status_code == 401
    assert client.get("/v1/households/h_042/cards", headers=_hub(key)).status_code == 401   # app routes: Bearer


# ------------------------------------------------------------------------------------------------ device list

def test_device_list_revisions(client):
    household()
    key = hub_key()
    body = fixture("ep_9031/devices.json")
    url = "/v1/hub/households/h_042/devices"
    r = client.put(url, json=body, headers=_hub(key))
    assert (r.status_code, r.json()) == (200, {"revision": 3})
    validate(r.json(), "devices_response.json")

    same = copy.deepcopy(body)
    same["devices"] = same["devices"][:1]
    assert client.put(url, json=same, headers=_hub(key)).json() == {"revision": 3}
    with session_scope() as s:
        assert len(s.get(DeviceList, "h_042").body["devices"]) == 7             # equal revision: no change

    old = {**copy.deepcopy(body), "revision": 2}
    r = client.put(url, json=old, headers=_hub(key))
    assert (r.status_code, r.json()["code"]) == (409, "stale_revision")
    validate(r.json(), "error.json")

    newer = {**copy.deepcopy(same), "revision": 4}
    assert client.put(url, json=newer, headers=_hub(key)).json() == {"revision": 4}
    with session_scope() as s:
        dl = s.get(DeviceList, "h_042")
        assert (dl.revision, len(dl.body["devices"])) == (4, 1)

    bad = copy.deepcopy(newer)
    bad["revision"] = 5
    del bad["devices"][0]["never"]
    r = client.put(url, json=bad, headers=_hub(key))
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    assert r.json()["details"]["path"].startswith("devices[0]")
    twice = {**copy.deepcopy(newer), "revision": 5, "devices": newer["devices"] * 2}
    r = client.put(url, json=twice, headers=_hub(key))
    assert r.json()["details"]["path"] == "devices[1].id"
    with session_scope() as s:
        assert s.get(DeviceList, "h_042").revision == 4


def test_unknown_device_type_accepted(client):
    household("h_051", types=["2인", "부부·커플"])
    key = hub_key("h_051")
    r = client.put("/v1/hub/households/h_051/devices", json=fixture("ep_9120/devices.json"), headers=_hub(key))
    assert r.status_code == 200                                                    # speaker (T34 part)


# --------------------------------------------------------------------------------------------------- calendar

def test_calendar_put_tags_in_background(client, app_headers, mock_llm):
    household()
    cal = fixture("ep_9031/calendar.json")
    events = [CalendarInput(**e) for e in cal["events"]]
    tags = {"c1": ["생일"], "c2": ["가족 모임"], "c3": ["회의"], "c4": [], "c5": []}
    mock_llm.record("cal", prompts.system("cal"), user_message(events),
                    output={"events": [{"id": i, "tags": t} for i, t in tags.items()]})
    r = client.put("/v1/households/h_042/calendar", json=cal, headers=app_headers)
    assert (r.status_code, r.json()) == (202, {"accepted": 5})
    validate(r.json(), "calendar_response.json")
    with session_scope() as s:                                                     # the background task ran
        assert {e.id: e.tags for e in s.execute(select(CalendarEvent)).scalars()} == tags

    r = client.put("/v1/households/h_999/calendar", json=cal, headers=app_headers)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")
    bad = {"events": [{"id": "c1", "title": "x", "start": "2026-10-17T14:00:00"}]}
    r = client.put("/v1/households/h_042/calendar", json=bad, headers=app_headers)
    assert (r.status_code, r.json()["code"]) == (422, "validation_error")
    assert r.json()["details"]["path"].startswith("events[0]")
    assert mock_llm.calls("cal") == 1


# ------------------------------------------------------------------------------------------------ cards poll

def test_t22_cards_poll(client, app_headers, mock_llm):
    _ep9031(mock_llm)
    clock.set_now(clock.parse("2026-10-15T21:12:00+09:00"))
    r = client.get("/v1/households/h_042/cards", headers=app_headers)
    assert r.status_code == 200
    validate(r.json(), "cards_response.json")
    assert r.json() == {"cards": [fixture("ep_9031/card.v1.json")], "server_time": "2026-10-15T21:12:00+09:00"}
    since = r.json()["server_time"]
    assert client.get("/v1/households/h_042/cards", params={"since": since},
                      headers=app_headers).json()["cards"] == []
    r = client.get("/v1/households/h_042/cards?since=2026-10-15T21:00:00 09:00", headers=app_headers)
    assert len(r.json()["cards"]) == 1                                             # unencoded '+' tolerated
    r = client.get("/v1/households/h_042/cards", params={"since": "yesterday"}, headers=app_headers)
    assert (r.status_code, r.json()["details"]["path"]) == (422, "since")
    assert client.get("/v1/households/h_999/cards", headers=app_headers).status_code == 404


def test_archived_card_returned_once_more(client, app_headers, mock_llm):
    _ep9031(mock_llm)
    clock.set_now(clock.parse("2026-10-16T09:00:00+09:00"))
    since = client.get("/v1/households/h_042/cards", headers=app_headers).json()["server_time"]
    with session_scope() as s:
        from spira_server.pipeline.s5_cards import touch
        card = s.get(Card, "nc_331")
        card.archived = True
        touch(s, card, clock.parse("2026-10-16T09:00:01+09:00"))
    clock.set_now(clock.parse("2026-10-16T09:00:30+09:00"))
    r = client.get("/v1/households/h_042/cards", params={"since": since}, headers=app_headers).json()
    assert [c["card_id"] for c in r["cards"]] == ["nc_331"] and r["cards"][0]["notify"] is False
    assert client.get("/v1/households/h_042/cards", params={"since": r["server_time"]},
                      headers=app_headers).json()["cards"] == []
    assert client.get("/v1/households/h_042/cards", headers=app_headers).json()["cards"] == []


# ------------------------------------------------------------------------------------------------ pull and ack

def _pull(client, key) -> dict:
    r = client.get("/v1/hub/plans", params={"household": "h_042"}, headers=_hub(key))
    assert r.status_code == 200
    validate(r.json(), "plan_pull.json")
    return r.json()


def test_pull_and_ack_v1(client, mock_llm):
    ep = _ep9031(mock_llm)
    key = hub_key()
    pull = _pull(client, key)
    assert pull == {"household_id": "h_042", "paused": False, "devices_revision": 3,
                    "plans": [fixture("ep_9031/plan.v1.json")]}
    clock.set_now(ACKED)
    r = client.post(f"/v1/hub/plans/{ep}/ack", json=fixture("ep_9031/ack.v1.json"), headers=_hub(key))
    assert (r.status_code, r.content) == (204, b"")
    with session_scope() as s:
        p = s.get(Plan, (ep, 1))
        assert (p.ack, clock.iso(p.acked_at)) == (fixture("ep_9031/ack.v1.json"), "2026-10-15T21:11:55+09:00")
        assert {t.status for t in s.execute(select(Task)).scalars()} == {"live"}
    assert [x["plan_version"] for x in _pull(client, key)["plans"]] == [1]        # live tasks keep it pulled

    r = client.post(f"/v1/hub/plans/{ep}/ack", json=fixture("ep_9031/ack.v1.json"), headers=_hub(key))
    assert r.status_code == 204                                                    # repeat: nothing else
    later = {"plan_version": 1, "status": "admitted", "rejected_tasks": [{"task_id": "t_mood#3", "reason": "schema"}]}
    assert client.post(f"/v1/hub/plans/{ep}/ack", json=later, headers=_hub(key)).status_code == 204
    with session_scope() as s:                                                     # first ack stands
        assert s.get(Plan, (ep, 1)).ack == fixture("ep_9031/ack.v1.json")
        assert s.get(Task, (ep, "t_mood#3")).status == "live"


def test_t31_ack_rejects_a_task(client, app_headers, mock_llm):
    ep = _ep9031(mock_llm)
    key = hub_key()
    clock.set_now(ACKED)
    since = client.get("/v1/households/h_042/cards", headers=app_headers).json()["server_time"]
    clock.set_now(clock.parse("2026-10-15T21:12:30+09:00"))
    ack = {"plan_version": 1, "status": "admitted", "rejected_tasks": [
        {"task_id": "t_mood#3", "reason": "value_out_of_range"}, {"task_id": "t_fridge#5", "reason": "schema"}]}
    assert client.post(f"/v1/hub/plans/{ep}/ack", json=ack, headers=_hub(key)).status_code == 204
    with session_scope() as s:
        tasks = {t.task_id: (t.status, t.drop_reason) for t in s.execute(select(Task)).scalars()}
    assert tasks["t_mood#3"] == tasks["t_fridge#5"] == ("dropped", "rejected")
    assert tasks["t_safe#2"] == ("live", None)
    clock.set_now(clock.parse("2026-10-15T21:13:00+09:00"))
    r = client.get("/v1/households/h_042/cards", params={"since": since}, headers=app_headers).json()
    [card] = r["cards"]
    validate(card, "card.json")
    mood = next(x for x in card["lines"] if x["task_id"] == "t_mood#3")
    assert (mood["state"], mood["note"]) == ("failed", "허브가 받지 못한 할 일이에요")
    assert card["notify"] is False and card["updated_at"] == "2026-10-15T21:12:30+09:00"
    assert card["summary"] == {"done": 0, "total": 4, "waiting_for": None}
    others = [x["state"] for x in card["lines"] if x["task_id"] != "t_mood#3"]
    assert others == ["scheduled", "scheduled", "scheduled"]


def test_t50_stale_whole_rejection_and_bad_acks(client, mock_llm):
    ep = _ep9031(mock_llm)
    key = hub_key()
    with session_scope() as s:                                                     # v2 adds one new task
        row = s.get(Task, (ep, "t_mood#3"))
        s.add(Task(episode_id=ep, task_id="t_extra#7", card_id=None, source="situation", way="run", status="live",
                   need="n", line="추가", actions=[{"device": "display_01", "cmd": "off"}],
                   trigger={"time": "2026-10-17T13:00:00+09:00"}, end=row.end, meta={}))
        s.flush()
        s5_plan.publish(s, _episode(s, ep), JUDGED, 3)

    stale = {"plan_version": 1, "status": "admitted", "rejected_tasks": [{"task_id": "t_mood#3", "reason": "schema"}]}
    assert client.post(f"/v1/hub/plans/{ep}/ack", json=stale, headers=_hub(key)).status_code == 204
    with session_scope() as s:
        assert s.get(Plan, (ep, 1)).ack == stale and s.get(Plan, (ep, 2)).ack is None
        assert s.get(Task, (ep, "t_mood#3")).status == "live"                     # newer version untouched

    whole = {"plan_version": 2, "status": "rejected", "rejected_tasks": []}
    assert client.post(f"/v1/hub/plans/{ep}/ack", json=whole, headers=_hub(key)).status_code == 204
    with session_scope() as s:
        tasks = {t.task_id: t.status for t in s.execute(select(Task)).scalars()}
    assert tasks.pop("t_extra#7") == "dropped" and set(tasks.values()) == {"live"}  # only the task new in v2

    for body, status, code in (
        ({"plan_version": 2, "status": "admitted", "rejected_tasks": [{"task_id": "t_none#9", "reason": "schema"}]},
         422, "validation_error"),
        ({"plan_version": 9, "status": "admitted", "rejected_tasks": []}, 404, "not_found"),
        ({"plan_version": 2, "status": "maybe", "rejected_tasks": []}, 422, "validation_error"),
    ):
        r = client.post(f"/v1/hub/plans/{ep}/ack", json=body, headers=_hub(key))
        assert (r.status_code, r.json()["code"]) == (status, code), body
        validate(r.json(), "error.json")
    r = client.post(f"/v1/hub/plans/{ep}/ack", json={"plan_version": 2, "status": "admitted", "rejected_tasks": [
        {"task_id": "t_none#9", "reason": "schema"}]}, headers=_hub(key))
    assert r.json()["details"]["path"] == "rejected_tasks[0].task_id"
    r = client.post("/v1/hub/plans/ep_404/ack", json=whole, headers=_hub(key))
    assert (r.status_code, r.json()["code"]) == (404, "not_found")


def test_pull_includes_paused_and_drops_finished(client, mock_llm):
    ep = _ep9031(mock_llm)
    key = hub_key()
    with session_scope() as s:
        s.get(Household, "h_042").paused = True
        s.get(Plan, (ep, 1)).ack = fixture("ep_9031/ack.v1.json")
        for t in s.execute(select(Task)).scalars():
            t.status = "ended"
        for line in s.execute(select(CardLine)).scalars():
            line.state = "done"
    assert _pull(client, key) == {"household_id": "h_042", "paused": True, "devices_revision": 3, "plans": []}
