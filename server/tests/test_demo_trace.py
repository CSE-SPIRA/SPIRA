"""GET /v1/demo/episodes/{id}/trace (contracts/openapi/demo.yaml, spec §12.5): stage states from stage times."""

from datetime import timedelta

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from sqlalchemy import select

from spira_server import clock
from spira_server.api.demo_routes import trace_body
from spira_server.db.engine import session_scope
from spira_server.db.models import Episode, LlmCall
from spira_server.main import create_app
from spira_server.paths import SERVER_DIR

from .s4_helpers import episode, household

T0 = clock.parse("2026-11-26T17:00:00+09:00")
CONTRACTS = SERVER_DIR.parent / "contracts"


def _times(**seconds: float) -> dict:
    return {k: clock.iso_ms(T0 + timedelta(seconds=v)) for k, v in seconds.items()}


def _set(ep: str, **values) -> None:
    with session_scope() as s:
        row = s.execute(select(Episode).where(Episode.id == ep).with_for_update()).scalar_one()
        for k, v in values.items():
            setattr(row, k, v)


def _trace(ep: str, at: float | None = None, now_s: float = 70) -> dict:
    with session_scope() as s:
        return trace_body(s, s.get(Episode, ep), at, now=T0 + timedelta(seconds=now_s))


def _states(body: dict) -> list[str]:
    return [x["state"] for x in body["stages"]]


def _validator():
    doc = yaml.safe_load((CONTRACTS / "openapi/demo.yaml").read_text(encoding="utf-8"))
    registry = Registry()
    for p in (CONTRACTS / "schemas").glob("*.json"):
        import json
        registry = registry.with_resource(f"../schemas/{p.name}", Resource.from_contents(json.loads(p.read_text())))
    trace = dict(doc["components"]["schemas"]["Trace"])
    trace["$defs"] = {"Stage": doc["components"]["schemas"]["Stage"]}
    text = yaml.safe_dump(trace).replace("#/components/schemas/Stage", "#/$defs/Stage")
    return Draft202012Validator(yaml.safe_load(text), registry=registry)


FULL = dict(received=0, s1_start=0.2, s1=14.8, s2=16.1, s3=29.5, s4=50.2, s5=51.0)


def test_live_and_replay():
    household()
    ep = episode()
    _set(ep, stage="done", status="notified", judged=True, stage_times=_times(**FULL))
    with session_scope() as s:
        s.add(LlmCall(episode_id=ep, stage="s1", provider="mock", model="m", input_tokens=5000, output_tokens=210,
                      latency_ms=13900, attempts=1, outcome="ok"))
        s.add(LlmCall(episode_id=ep, stage="s3", provider="mock", model="m", input_tokens=4000, output_tokens=300,
                      latency_ms=12000, attempts=1, outcome="ok"))

    body = _trace(ep)
    _validator().validate(body)
    assert body["mode"] == "live" and body["finished"] and _states(body) == ["done"] * 5
    assert [x["done_s"] for x in body["stages"]] == [14.8, 16.1, 29.5, 50.2, 51.0]
    assert body["stages"][0]["llm"] == {"calls": 1, "ms": 13900, "input_tokens": 5000, "output_tokens": 210}
    assert body["stages"][1]["llm"] is None and body["stages"][3]["llm"] is None      # no LLM call recorded

    body = _trace(ep, at=20)
    _validator().validate(body)
    assert body["mode"] == "replay" and body["elapsed_s"] == 20 and not body["finished"]
    assert _states(body) == ["done", "done", "running", "pending", "pending"]
    assert body["stages"][2]["done_s"] is None and body["stages"][2]["llm"] is None
    assert _states(_trace(ep, at=0.1)) == ["pending"] * 5                     # S1 had not begun
    assert _states(_trace(ep, at=1)) == ["running"] + ["pending"] * 4
    assert _trace(ep, at=999)["finished"]


def test_results_are_stored_values_gated_by_stage():
    household()
    ep = episode()
    ctx = {"for_intent": {"this_home": {"household_types": ["3~4인"], "calendar": [{"id": "c1", "tags": ["생일"]}],
                                        "unusual_items": {"status": "list", "items": [{"item": "풍선", "why": "처음 산 물건"}]}},
                          "kb_neighbors": {"similar_count": 12, "base_total": 1000, "note": None,
                                           "intent_counts": [{"intent_id": "kid_birthday_party", "name": "아이 생일 파티",
                                                              "n": 9, "share": 0.75, "base_share": 0.02}]}},
           "snapshot": [], "kb_search": {"searched": 200, "sim_floor": 0.7, "above_floor": 126, "used": 50,
                                         "sims": [0.86], "top": []}}
    s4 = {"llm_called": True, "whens": {}, "skipped_bundles": {}, "drafts": [{"task_id": "t_clean#1"}], "dropped": []}
    _set(ep, stage="s2", status="reading", context=ctx, s4=s4,
         stage_times=_times(received=0, s1_start=0.2, s1=14.8, s2=16.1, s3=29.5, s4=50.2))
    body = _trace(ep, at=20)
    _validator().validate(body)
    r1, r2, r3 = (x["result"] for x in body["stages"][:3])
    assert len(r1["items"]) == 9 and r1["items"][0]["type"] and r1["error"] is None
    assert r2["unusual_items"]["items"][0]["item"] == "풍선" and r2["kb"]["intent_counts"][0]["base_share"] == 0.02
    assert r2["kb_search"]["above_floor"] == 126
    assert r3 is None                                                       # S3 not done at 20 s
    body = _trace(ep, at=60)
    assert body["stages"][2]["result"]["bundles"][0]["intent_id"] == "kid_birthday_party"
    assert body["stages"][3]["result"]["drafts"][0]["task_id"] == "t_clean#1"   # S4 before S5
    assert body["stages"][4]["result"] is None
    from spira_server.db.models import Task
    with session_scope() as s:
        s.add(Task(task_id="t_clean#1", episode_id=ep, source="situation", way="run", end={},
                   actions=[{"device": "cleaner_01", "cmd": "clean"}], status="dropped", drop_reason="late",
                   line="손님 오기 전 거실 청소", meta={}))
    _set(ep, stage="done", stage_times=_times(received=0, s1_start=0.2, s1=14.8, s2=16.1, s3=29.5, s4=50.2, s5=51))
    r5 = _trace(ep)["stages"][4]["result"]
    assert r5["cards"] == [] and r5["dropped"] == [{"task_id": "t_clean#1", "source": "situation",
                                                    "line": "손님 오기 전 거실 청소", "item": None, "reason": "late"}]


def test_live_running_and_failures():
    household()
    ep = episode()
    _set(ep, stage="s2", status="reading", stage_times=_times(received=0, s1_start=0.1, s1=12, s2=13))
    body = _trace(ep, now_s=20)
    assert _states(body) == ["done", "done", "running", "pending", "pending"] and body["elapsed_s"] == 20

    _set(ep, stage="done", status="judged", error={"stage": "s2", "message": "KB unavailable"})
    assert _states(_trace(ep)) == ["done", "failed", "skipped", "skipped", "skipped"]

    _set(ep, status="read_failed", error=None, stage_times=_times(received=0, s1_start=0.1, s1=9))
    body = _trace(ep)
    assert _states(body) == ["failed", "skipped", "skipped", "skipped", "skipped"] and body["finished"]


def test_old_episode_without_times():
    household()
    ep = episode()
    _set(ep, stage="done", status="judged", judged=True, stage_times={})
    body = _trace(ep)
    _validator().validate(body)
    assert body["started_at"] is None and body["elapsed_s"] is None and _states(body) == ["done"] * 5


def test_route_demo_only(env, app_headers):
    household()
    ep = episode()
    client = TestClient(create_app(start_background=False))
    assert client.get(f"/v1/demo/episodes/{ep}/trace", headers=app_headers).status_code == 404     # DEMO_MODE=0
    env(DEMO_MODE="1")
    client = TestClient(create_app(start_background=False))
    r = client.get(f"/v1/demo/episodes/{ep}/trace", headers=app_headers, params={"at": 3.5})
    assert r.status_code == 200 and r.json()["at"] == 3.5
    assert client.get(f"/v1/demo/episodes/{ep}/trace", headers=app_headers, params={"at": -1}).status_code == 422
    assert client.get("/v1/demo/episodes/ep_404/trace", headers=app_headers).status_code == 404
    assert client.get(f"/v1/demo/episodes/{ep}/trace").status_code == 401


def test_reset_keeps_the_hub_key_and_the_seeded_home(env, app_headers, tmp_path):
    from spira_server.db.models import Household
    text = (SERVER_DIR / "dev/home.example.yaml").read_text(encoding="utf-8")
    text = text[: text.index("\ncalendar:")] + text[text.index("\npast_orders:"):]      # no LLM tagging in tests
    text = text.replace("devices_from: ../../contracts", f"devices_from: {CONTRACTS}")
    home = tmp_path / "home.yaml"
    home.write_text(text, encoding="utf-8")
    household()
    ep = episode()
    with session_scope() as s:
        before = s.get(Household, "h_042").hub_key_hash
    env(DEMO_MODE="1", DEMO_HOME=str(home))
    client = TestClient(create_app(start_background=False))
    r = client.post("/v1/demo/households/h_042/reset", headers=app_headers)
    assert r.status_code == 200 and r.json()["past_orders"] == 12 and r.json()["household_id"] == "h_042"
    with session_scope() as s:
        assert s.get(Household, "h_042").hub_key_hash == before                 # a running hub keeps working
        assert s.get(Episode, ep) is None                                        # test orders are gone
        assert s.query(Episode).filter(Episode.household_id == "h_042").count() == 12
    assert client.post("/v1/demo/households/h_404/reset", headers=app_headers).status_code == 404
    env(DEMO_MODE="0")
    client = TestClient(create_app(start_background=False))
    assert client.post("/v1/demo/households/h_042/reset", headers=app_headers).status_code == 404


def test_kept_episode_survives_reset_in_the_replay_archive(env, app_headers, tmp_path):
    from spira_server.db.models import Task
    text = (SERVER_DIR / "dev/home.example.yaml").read_text(encoding="utf-8")
    text = text[: text.index("\ncalendar:")] + text[text.index("\npast_orders:"):]
    text = text.replace("devices_from: ../../contracts", f"devices_from: {CONTRACTS}")
    home = tmp_path / "home.yaml"
    home.write_text(text, encoding="utf-8")
    household()
    kept, other = episode(), episode("ep_9032")
    _set(kept, judged=True, status="notified", stage="done", stage_times=_times(**FULL))
    with session_scope() as s:
        s.add(Task(task_id="t_clean#1", episode_id=kept, source="situation", way="run", end={}, status="live",
                   actions=[{"device": "cleaner_01", "cmd": "clean"}], line="거실 청소", meta={}))
    env(DEMO_MODE="1", DEMO_HOME=str(home))
    client = TestClient(create_app(start_background=False))
    assert client.post(f"/v1/demo/episodes/{other}/keep", headers=app_headers).status_code == 400   # not judged
    r = client.post(f"/v1/demo/episodes/{kept}/keep", headers=app_headers)
    assert r.status_code == 200 and r.json() == {"episode_id": kept, "kept": True}
    listed = client.get("/v1/demo/households/h_042/replays", headers=app_headers).json()["replays"]
    assert [(x["episode_id"], x["duration_s"], x["parked"]) for x in listed] == [(kept, 51.0, False)]

    r = client.post("/v1/demo/households/h_042/reset", headers=app_headers)
    assert r.status_code == 200 and r.json()["replays_kept"] == 1
    with session_scope() as s:
        assert s.get(Episode, other) is None
        assert s.get(Episode, kept).household_id == "h_042replay"          # out of the live household
        assert s.get(Task, (kept, "t_clean#1")).status == "cancelled"      # nothing left to run or merge with
    listed = client.get("/v1/demo/households/h_042/replays", headers=app_headers).json()["replays"]
    assert [(x["episode_id"], x["parked"]) for x in listed] == [(kept, True)]
    trace = client.get(f"/v1/demo/episodes/{kept}/trace", headers=app_headers, params={"at": 20}).json()
    assert [x["state"] for x in trace["stages"]] == ["done", "done", "running", "pending", "pending"]
    assert client.post("/v1/demo/households/h_042/reset", headers=app_headers).json()["replays_kept"] == 0
    with session_scope() as s:
        assert s.get(Episode, kept) is not None                              # the archive is never reset
    assert client.post(f"/v1/demo/episodes/{kept}/keep", headers=app_headers, json={"keep": False}).json()["kept"] is False


def test_household_status_for_the_idle_console(env, app_headers, tmp_path):
    from spira_server.db.models import CalendarEvent, DeviceList
    household()
    ep = episode()
    with session_scope() as s:
        s.add(DeviceList(household_id="h_042", revision=1, body={"devices": [
            {"id": "a", "room": "거실"}, {"id": "b", "room": "거실"}, {"id": "c", "room": "주방"}]}))
        now = clock.now()
        s.add(CalendarEvent(household_id="h_042", id="c1", start=now + timedelta(minutes=20),
                            end=now + timedelta(minutes=80), tags=["birthday"], tagged=True, fingerprint="x"))
        s.add(CalendarEvent(household_id="h_042", id="c0", start=now - timedelta(days=2),
                            end=now - timedelta(days=2, hours=-1), tags=[], tagged=False, fingerprint="y"))
    env(DEMO_MODE="1")
    client = TestClient(create_app(start_background=False))
    body = client.get("/v1/demo/households/h_042/status", headers=app_headers).json()
    assert body["devices"] == {"count": 3, "rooms": {"거실": 2, "주방": 1}}
    assert body["orders"]["count"] == 1 and body["orders"]["latest"]["episode_id"] == ep
    assert [(e["id"], e["tags"]) for e in body["calendar"]] == [("c1", ["birthday"])]      # ended events left out
    assert client.get("/v1/demo/households/h_999/status", headers=app_headers).status_code == 404
    env(DEMO_MODE="0")
    assert TestClient(create_app(start_background=False)).get(
        "/v1/demo/households/h_042/status", headers=app_headers).status_code == 404
