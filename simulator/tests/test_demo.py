import json
import shutil
import subprocess
from pathlib import Path

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
    monkeypatch.delenv("DEMO_NUMBERS_PATH", raising=False)
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
        "household_id": "h_042", "server": True, "hub": False, "fixture": False, "story_timing": None,
    }


def test_story_time_uses_server_numbers_and_hub_schedule(client, monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to exercise the demo's display module")
    numbers = Path(__file__).resolve().parents[2] / "server/config/numbers.yaml"
    monkeypatch.setenv("DEMO_NUMBERS_PATH", str(numbers))
    monkeypatch.setenv("DEMO_HUB_URL", "http://hub.test")
    starts = "2026-11-20T11:42:11+09:00"
    ends = "2026-11-20T11:42:41+09:00"
    cleaning = "2026-11-20T11:39:11+09:00"
    safety = "2026-11-20T11:41:11+09:00"
    fallback = "2026-11-20T11:52:41+09:00"
    dispatched = "2026-11-20T11:40:45+09:00"
    ledger = [
        {"kind": "run", "at": dispatched, "operation_id": "op_clean"},
        {"kind": "event", "at": safety, "event_type": "guest_arrived"},
        {"kind": "restore", "at": "2026-11-20T11:52:42+09:00", "reports": [{"kind": "restore", "id": "rs_end"}]},
    ]

    async def fake_get(self, url):
        return httpx.Response(200, json={"ledger": ledger, "task_stories": [
            {"plan_id": "ep_9031", "task_id": "t_clean#1", "steps": [
                {"kind": "waiting", "trigger": {"time": cleaning}},
                {"kind": "triggered", "how": "time", "at": cleaning},
                {"kind": "command", "phase": "run", "at": dispatched, "operation_id": "op_clean"},
            ]},
            {"plan_id": "ep_9031", "task_id": "t_mood#3", "steps": [
                {"kind": "waiting", "trigger": {"event": "guest_arrived", "window": {"from": safety, "to": ends}}},
                {"kind": "end", "how": "fallback", "rule": "or_time", "at": fallback},
                {"kind": "restore_result", "result_id": "rs_end", "at": ledger[2]["at"]},
            ]},
        ]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    timing = client.get("/demo/api/config").json()["story_timing"]
    hub = client.get("/demo/api/hub").json()
    assert [row["at"] for row in hub["ledger"]] == [row["at"] for row in ledger]

    # Run the same formatter as the card, timeline and ledger without a browser.
    script = """
        import assert from 'node:assert/strict';
        import { readFileSync } from 'node:fs';
        const source = readFileSync(process.argv[1]).toString('base64');
        const { displayTime, storyClock, storyLedgerTime, storyObservedTime, storyPlanTime } =
          await import(`data:text/javascript;base64,${source}`);
        const { timing, hub, starts, cleaning, safety, fallback } = JSON.parse(readFileSync(0, 'utf8'));
        const event = { day: '토', start: '14:00', end: '17:00' };
        const ends = hub.guest_windows.ep_9031['t_mood#3'].to;
        const story = storyClock(event, starts, ends, timing);
        const planTime = (at) => displayTime(storyPlanTime(at, story));
        assert.equal(planTime(cleaning), '토 12:30');
        assert.equal(planTime(safety), '토 13:30');
        assert.equal(planTime(starts), '토 14:00');
        assert.equal(planTime('2026-11-20T11:37:11+09:00'), '토 13:55');
        assert.equal(planTime(ends), '토 17:00');
        assert.equal(planTime(fallback), '토 20:00');
        assert.equal(storyLedgerTime(hub.ledger[0], story), '토 12:30');
        assert.equal(storyLedgerTime(hub.ledger[1], story, '손님 도착'), '손님 도착');
        assert.equal(storyLedgerTime(hub.ledger[2], story), '토 20:00');
        assert.equal(storyObservedTime('2026-11-20T11:41:41+09:00', story, '손님 도착'), '토 13:59');
        const unconfigured = storyClock(event, starts, ends, null);
        assert.equal(displayTime(storyPlanTime(cleaning, unconfigured)), '토 13:57');
        assert.equal(storyLedgerTime(hub.ledger[0], unconfigured), '토 13:58');
    """
    subprocess.run(
        [node, "--input-type=module", "-e", script, str(demo.DEMO_UI / "story-time.js")],
        input=json.dumps(dict(timing=timing, hub=hub, starts=starts, cleaning=cleaning, safety=safety, fallback=fallback)),
        text=True, check=True,
    )


def test_story_timing_falls_back_when_numbers_file_is_missing(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_NUMBERS_PATH", str(tmp_path / "missing.yaml"))
    assert client.get("/demo/api/config").json()["story_timing"] is None


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
        "ledger": ledger, "waiting": waiting, "guest_windows": {},
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
    assert client.get("/demo/api/hub").json() == {"ledger": [], "waiting": [], "guest_windows": {}, "plan_actions": {}}
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
