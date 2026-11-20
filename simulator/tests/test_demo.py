import httpx
import pytest
from fastapi.testclient import TestClient
from spira_simulator import demo
from spira_simulator.api import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLD_DEMO", "1")
    monkeypatch.setenv("DEMO_SERVER_URL", "http://server.test")
    monkeypatch.setenv("DEMO_APP_TOKEN", "t")
    monkeypatch.delenv("DEMO_HUB_URL", raising=False)
    with TestClient(create_app(tmp_path / "world.db", broker_enabled=False)) as test_client:
        yield test_client


def test_demo_is_off_unless_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("WORLD_DEMO", raising=False)
    with TestClient(create_app(tmp_path / "world.db", broker_enabled=False)) as off:
        assert off.get("/demo").status_code == 404


def test_page_assets_and_config(client):
    assert client.get("/demo").status_code == 200
    for name in ("demo.js", "house.js", "flow.js", "story-time.js", "tokens.css", "scenes.json", "three.module.min.js"):
        assert client.get(f"/demo/assets/{name}").status_code == 200, name
    assert client.get("/demo/assets/..%2Fapi.py").status_code == 404
    assert client.get("/demo/api/config").json() == {
        "household_id": "h_042", "server": True, "hub": False, "fixture": False,
    }


def test_server_proxy_reads_only_contract_routes(client, monkeypatch):
    seen = []

    async def fake_get(self, url, **kwargs):
        seen.append((url, kwargs["headers"]))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert client.get("/demo/api/server/v1/episodes/ep_9031/rationale").json() == {"ok": True}
    assert seen == [("http://server.test/v1/episodes/ep_9031/rationale", {"Authorization": "Bearer t"})]
    for path in ("v1/hub/plans", "_fixture/receipts", "v1/cards/nc_1/reactions"):
        assert client.get(f"/demo/api/server/{path}").status_code == 404


def test_hub_proxy_reads_state_and_projects_latest_received_actions(client, monkeypatch):
    monkeypatch.setenv("DEMO_HUB_URL", "http://hub.test")
    seen = []
    ledger = [{"kind": "plan", "plan_id": "ep_9031", "plan_version": n} for n in (1, 2)]
    color = {"device": "light_01", "cmd": "color", "value": {"hue": 330, "saturation": 45, "brightness": 70}}
    waiting = [
        {"plan_id": "ep_9031", "plan_version": 2, "task_id": "t_mood#3", "actions": [color]},
        {"plan_id": "ep_9031", "plan_version": 1, "task_id": "t_removed#4",
         "actions": [{"device": "oven_01", "cmd": "set_cook_standby"}]},
    ]
    stories = [
        {"plan_id": "ep_9031", "task_id": "t_mood#3", "steps": [
            {"kind": "admitted", "plan_version": 1},
            {"kind": "command", "phase": "run", "plan_version": 1, "device": "display_01",
             "cmd": "play_mood", "desired": {"play_mood": {"scene": "kids_party"}}},
            {"kind": "admitted", "plan_version": 2},
            {"kind": "command", "phase": "restore", "plan_version": 2, "device": "display_01",
             "cmd": "play_mood", "desired": {"play_mood": {"scene": "calm"}}},
        ]},
        {"plan_id": "ep_9031", "task_id": "t_removed#4", "steps": [
            {"kind": "admitted", "plan_version": 1}, {"kind": "removed", "plan_version": 2},
        ]},
    ]

    async def fake_get(self, url):
        seen.append(url)
        return httpx.Response(200, json={
            "ledger": ledger, "waiting": waiting, "task_stories": stories, "devices": ["internal"],
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert client.get("/demo/api/hub?path=/commands").json() == {
        "ledger": ledger, "waiting": waiting,
        "plan_actions": {"ep_9031": {"t_mood#3": [
            color, {"device": "display_01", "cmd": "play_mood", "value": {"scene": "kids_party"}},
        ]}},
    }
    assert client.post("/demo/api/hub").status_code == 405
    assert client.get("/demo/api/hub/commands").status_code == 404
    assert seen == ["http://hub.test/state"]


def test_hub_proxy_handles_unconfigured_empty_and_failed_state(client, monkeypatch):
    assert client.get("/demo/api/hub").status_code == 503
    monkeypatch.setenv("DEMO_HUB_URL", "http://hub.test")
    responses = iter([httpx.Response(200, json={}), httpx.Response(503, json={"detail": "upstream"})])

    async def fake_get(self, url):
        return next(responses)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert client.get("/demo/api/hub").json() == {"ledger": [], "waiting": [], "plan_actions": {}}
    assert client.get("/demo/api/hub").status_code == 502


def test_timeline_events_are_world_home_events(client):
    assert client.post("/demo/api/home/guests_arrive").json() == {"applied": True}
    assert client.post("/demo/api/home/open_fridge").status_code == 404
    assert client.post(
        "/demo/api/home/delivery", headers={"Origin": "http://elsewhere.test"}
    ).status_code == 403


def test_scenes_follow_the_server_pipeline():
    scenes = (demo.DEMO_UI / "scenes.json").read_text(encoding="utf-8")
    for stage in ("extract", "context", "intent", "tasks", "plan"):
        assert f'"id": "{stage}"' in scenes
