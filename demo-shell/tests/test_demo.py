import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import demo


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DEMO_SERVER_URL", "http://server.test")
    monkeypatch.setenv("DEMO_APP_TOKEN", "t")
    monkeypatch.delenv("DEMO_HUB_URL", raising=False)
    monkeypatch.delenv("DEMO_NUMBERS_PATH", raising=False)
    monkeypatch.delenv("DEMO_FIXTURE_EPISODE", raising=False)
    monkeypatch.setenv("DEMO_HOUSEHOLD", "h_042")
    monkeypatch.setenv("DEMO_SIMULATOR_URL", "http://sim.test")
    with TestClient(demo.create_app()) as test_client:
        yield test_client


def test_page_assets_and_config(client):
    page = client.get("/demo").raise_for_status().text
    for name in ("demo.js", "chain.js", "flow.js", "story-time.js", "scenes.json"):
        assert client.get(f"/demo/assets/{name}").status_code == 200, name
    for name in ("house.css", "tokens.css", "fonts.css", "viewer.css"):
        assert f'href="/sim/assets/house/{name}"' in page
    script = client.get("/demo/assets/demo.js").raise_for_status().text
    assert 'from "/sim/assets/house/house.js"' in script
    assert 'className = "marker-trace"' in script
    assert 'fetch("/demo/api/sim/viewer"' in script
    assert client.get("/demo/assets/house.js").status_code == 404
    assert client.get("/demo/assets/..%2Fdemo.py").status_code == 404
    assert client.get("/demo/api/config").json() == {
        "household_id": "h_042", "server": True, "hub": False, "fixture": False, "story_timing": None,
    }


def test_shell_reads_house_assets_and_viewer_over_http(client, monkeypatch):
    seen = []

    async def fake_get(self, url, headers):
        seen.append((url, headers))
        return httpx.Response(200, text="Simulator response", headers={"content-type": "text/css"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    asset = client.get("/sim/assets/house/tokens.css", headers={"If-None-Match": '"tokens"'})
    assert asset.headers["content-type"] == "text/css"
    assert asset.text == "Simulator response"
    assert client.get("/demo/api/sim/viewer?fragment=false").text == "Simulator response"
    assert client.get("/demo/api/sim/snapshot").text == "Simulator response"
    assert client.get("/demo/api/sim/operator").status_code == 404
    assert client.get("/sim/assets/house/..%2F..%2F..%2Foperator").status_code == 404
    assert seen == [
        ("http://sim.test/sim/assets/house/tokens.css", {"if-none-match": '"tokens"'}),
        ("http://sim.test/sim/viewer?fragment=true", None),
        ("http://sim.test/sim/snapshot", None),
    ]


def test_fixture_config_exposes_recorded_capture_times(client, monkeypatch):
    monkeypatch.setenv("DEMO_FIXTURE_EPISODE", "ep_9031")
    assert client.get("/demo/api/config").json()["fixture_shares"] == {
        "ep_9031": "2026-10-15T21:00:08+09:00",
        "ep_9150": "2026-11-04T19:30:41+09:00",
    }


def test_evidence_chain():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to test the demo's evidence chain")
    subprocess.run([node, "--test", str(Path(__file__).with_name("demo_chain.test.mjs"))], check=True)


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
    package = "package.brought_in"
    released = {"event": package, "released": True, "at": safety}
    ledger = [
        {"kind": "run", "at": dispatched, "operation_id": "op_clean"},
        {"kind": "event", "at": safety, "event_type": "guest_arrived"},
        {"kind": "restore", "at": "2026-11-20T11:52:42+09:00", "reports": [{"kind": "restore", "id": "rs_end"}]},
        {"kind": "event", "at": safety, "event_type": package},
        {"kind": "plan", "plan_id": "ep_9031", "plan_version": 2, "at": safety},
        {"kind": "run", "device": "fridge_01", "at": safety, "operation_id": "op_notice"},
    ]

    async def fake_get(self, url):
        return httpx.Response(200, json={"ledger": ledger, "plan_history": [
            {"plan_id": "ep_9031", "plan_version": 2, "changes": {"triggers_changed": [
                {"from": {"event": package, "released": False}, "to": released},
            ]}},
        ], "task_stories": [
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
            {"plan_id": "ep_9031", "task_id": "t_fridge#5", "steps": [
                {"kind": "waiting", "trigger": released},
                {"kind": "triggered", "how": "server_release", "event_type": package, "at": safety},
                {"kind": "command", "phase": "run", "at": safety, "operation_id": "op_notice"},
            ]},
        ]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    timing = client.get("/demo/api/config").json()["story_timing"]
    hub = client.get("/demo/api/hub").json()
    assert timing["quiet_s"] == {"normal": 600, "demo": 30}
    assert [row["at"] for row in hub["ledger"]] == [row["at"] for row in ledger]
    assert hub["ledger"][4]["timing"]["event"] == package
    assert hub["ledger"][5]["timing"]["event"] == package

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


def test_timeline_events_are_world_home_events(client, monkeypatch):
    monkeypatch.setenv("DEMO_OPERATOR_TOKEN", "test-operator-token")
    seen = []

    async def fake_post(self, url, *, auth, json):
        seen.append((url, auth, json))
        return httpx.Response(200, json={"applied": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert client.post("/demo/api/home/guests_arrive").json() == {"applied": True}
    assert client.post("/demo/api/home/open_fridge").status_code == 404
    assert client.post(
        "/demo/api/home/delivery", headers={"Origin": "http://elsewhere.test"}
    ).status_code == 403
    assert seen == [
        ("http://sim.test/operator/home", ("operator", "test-operator-token"), {"action": "guests_arrive"}),
    ]


def test_scenes_follow_the_server_pipeline():
    scenes = (demo.DEMO_UI / "scenes.json").read_text(encoding="utf-8")
    for stage in ("extract", "context", "intent", "tasks", "plan"):
        assert f'"id": "{stage}"' in scenes
