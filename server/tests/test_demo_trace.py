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
