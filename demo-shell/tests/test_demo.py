import asyncio
import json
import shutil
import subprocess
from threading import Event
from time import monotonic, sleep
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import demo
import tagger


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_RECORDINGS_DIR", str(tmp_path))
    monkeypatch.setenv("DEMO_TAGGER", "off")
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
    for name in ("demo.js", "chain.js", "flow.js", "story-time.js", "wire.js", "judgment.js",
                 "judgment-view.js", "markup.js", "scenes.json", "item-types.json", "tags.js"):
        assert client.get(f"/demo/assets/{name}").status_code == 200, name
    for name in ("tokens.css", "fonts.css"):
        assert f'href="/demo/shared/{name}"' in page
        assert client.get(f"/demo/shared/{name}").status_code == 200
    assert client.get("/demo/shared/vocabulary.js").status_code == 200
    script = client.get("/demo/assets/demo.js").raise_for_status().text
    assert 'import(base + "house.js")' in script
    assert 'className = "marker-moment"' in script
    assert 'observe("viewer", "/demo/api/sim/viewer"' in script
    assert client.get("/demo/assets/house.js").status_code == 404
    assert client.get("/demo/assets/wire-view.js").status_code == 404
    assert client.get("/demo/assets/..%2Fdemo.py").status_code == 404
    assert client.get("/demo/api/config").json() == {
        "household_id": "h_042", "server": True, "hub": False, "fixture": False, "story_timing": None, "tagger": False,
    }


def test_reset_requires_loopback_and_same_origin_and_forwards_launcher_status(client, monkeypatch):
    path = "/demo/api/reset"
    url = "http://127.0.0.1:8729/reset"
    monkeypatch.setenv("DEMO_RESET_URL", url)
    monkeypatch.setenv("DEMO_RESET_TOKEN", "test-reset-token")
    forwarded = []
    statuses = iter([204, 409, 503])

    async def upstream(self, target, *, headers):
        forwarded.append((target, headers))
        return httpx.Response(next(statuses))

    monkeypatch.setattr(httpx.AsyncClient, "post", upstream)
    with TestClient(client.app, base_url="http://localhost", client=("192.0.2.1", 12345)) as remote:
        assert remote.post(path, headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    with TestClient(client.app, base_url="http://localhost", client=("127.0.0.1", 12345)) as local:
        assert local.get("/demo/api/config").json()["reset"] is True
        assert "test-reset-token" not in local.get("/demo/api/config").text
        assert local.post(path, headers={"Origin": "http://elsewhere.test"}).status_code == 403
        assert local.post(path, headers={"Host": "elsewhere.test"}).status_code == 403
        assert forwarded == []
        for status in (204, 409, 503):
            assert local.post(path, headers={"Origin": "http://localhost"}).status_code == status
        assert forwarded == [(url, {"Authorization": "Bearer test-reset-token"})] * 3
        monkeypatch.delenv("DEMO_RESET_URL")
        assert local.post(path).status_code == 503
        assert len(forwarded) == 3


def test_artwork_preview_is_a_read_only_page_on_the_presenter_loopback(client):
    path = "/demo/artwork"
    assert client.get(path).status_code == 404
    with TestClient(client.app, base_url="http://localhost", client=("127.0.0.1", 12345)) as presenter:
        page = presenter.get(path).raise_for_status()
        assert page.headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
        assert 'id="artwork-gallery"' in page.text
        assert presenter.get("/demo/assets/artwork/preview.js").status_code == 200
        assert presenter.get("/demo/assets/artwork-preview.html").status_code == 404
        assert presenter.get(path, headers={"Origin": "http://elsewhere.test"}).status_code == 403
        assert presenter.post(path).status_code == 405
    with TestClient(client.app, base_url="http://localhost", client=("192.0.2.1", 12345)) as remote:
        assert remote.get(path).status_code == 404


def test_house_assets_come_from_simulator_http_and_live_waits_when_it_is_down(client, monkeypatch):
    assert "simulator/spira_simulator" not in Path(demo.__file__).read_text()
    assert not hasattr(demo, "HOUSE_UI")
    seen = []
    available = False

    async def fake_get(self, url, headers):
        seen.append((url, headers))
        if not available:
            raise httpx.ConnectError("Simulator stopped")
        return httpx.Response(200, text="Simulator response", headers={"content-type": "text/css"})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    path = "/sim/assets/house/tokens.css"
    assert client.get(path).status_code == 502
    assert client.get("/demo/shared/tokens.css").status_code == 200
    available = True
    asset = client.get(path)
    assert asset.headers["content-type"].startswith("text/css")
    assert asset.text == "Simulator response"
    assert client.get("/demo/api/sim/viewer?fragment=false").text == "Simulator response"
    assert client.get("/demo/api/sim/snapshot").text == "Simulator response"
    assert client.get("/demo/api/sim/operator").status_code == 404
    assert client.get("/sim/assets/house/..%2F..%2F..%2Foperator").status_code == 404
    available = False
    assert client.get(path).status_code == 502
    assert client.get("/demo/replay-house/tokens.css").text == "Simulator response"
    assert seen == [
        ("http://sim.test/sim/assets/house/tokens.css", None),
        ("http://sim.test/sim/assets/house/tokens.css", None),
        ("http://sim.test/sim/viewer?fragment=true", None),
        ("http://sim.test/sim/snapshot", None),
        ("http://sim.test/sim/assets/house/tokens.css", None),
    ]


def test_shell_has_no_simulator_screen_proxy(client):
    assert client.get("/sim/screens/tv", params={"scene": "kids_party"}).status_code == 404


def test_fixture_mode_only_changes_the_config_flag(client, monkeypatch):
    ordinary = client.get("/demo/api/config").json()
    monkeypatch.setenv("DEMO_FIXTURE_EPISODE", "ep_9031")
    assert client.get("/demo/api/config").json() == {**ordinary, "fixture": True}


@pytest.mark.parametrize("fixture_mode", [True, False], ids=["fixture", "real"])
def test_grocery_share_selects_recording_only_on_fixture(client, monkeypatch, fixture_mode):
    expected_headers = {"Authorization": "Bearer t"}
    expected_requests = []
    if fixture_mode:
        monkeypatch.setenv("DEMO_FIXTURE_EPISODE", "ep_9031")
        expected_headers["X-SPIRA-Demo-Client"] = "shell"
        expected_requests.append(("http://server.test/_fixture/scene/next-order", {
            "json": {"episode_id": "ep_9150"},
        }))
    image = ("groceries.png", b"grocery screenshot", "image/png")
    expected_requests.append(("http://server.test/v1/orders", {
        "data": {"household_id": "h_042"}, "files": [("images", image)],
    }))
    seen = []

    async def post(self, url, *, headers, **kwargs):
        assert headers == expected_headers
        seen.append((url, kwargs))
        if url.endswith("/next-order"):
            return httpx.Response(202, json={"episode_id": "ep_9150"})
        return httpx.Response(202, json={"episode_id": "ep_9150", "status": "received"})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    receipt = client.post("/demo/api/order", data={"sample": "groceries"}, files={"images": image})
    assert receipt.status_code == 202
    assert receipt.json() == {"episode_id": "ep_9150", "status": "received"}
    assert seen == expected_requests


@pytest.mark.parametrize(("reaction", "status", "body"), [
    ({"reaction": "line_off", "task_id": "t_clean#1"}, 200, {"card_id": "nc_331"}),
    ({"reaction": "line_on", "task_id": "t_clean#1"}, 409, {"code": "line_started", "message": "Started"}),
    ({"reaction": "stop"}, 200, {"card_id": "nc_331", "stopped": True}),
])
def test_reaction_forwards_contract_body_and_preserves_result(client, monkeypatch, reaction, status, body):
    seen = []

    async def post(self, url, *, json, headers):
        seen.append((url, json))
        return httpx.Response(status, json=body)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    receipt = client.post("/demo/api/reaction", json={"card_id": "nc_331", **reaction})
    assert receipt.status_code == status
    assert receipt.json() == body
    assert seen == [("http://server.test/v1/cards/nc_331/reactions", reaction)]


@pytest.mark.parametrize("reaction", [
    {"reaction": "stop", "task_id": None},
    {"reaction": "line_off"},
    {"reaction": "line_on", "task_id": "invalid"},
])
def test_reaction_rejects_invalid_task_scope(client, reaction):
    assert client.post("/demo/api/reaction", json={"card_id": "nc_331", **reaction}).status_code == 400


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
    ledger = [
        {"kind": "plan", "plan_id": "ep_9031", "plan_version": 1, "at": cleaning},
        {"kind": "event", "at": safety, "event_type": "guest_arrived"},
        {"kind": "run", "at": safety, "operation_id": "op_clean"},
        {"kind": "event", "at": safety, "event_type": "cleaner.completed"},
        {"kind": "event", "at": ends, "event_type": "light.changed", "by": "user"},
    ]

    async def fake_get(self, url):
        return httpx.Response(200, json={"ledger": ledger, "task_stories": [
            {"plan_id": "ep_9031", "task_id": "t_mood#3", "steps": [
                {"kind": "waiting", "trigger": {"event": "guest_arrived", "window": {"from": safety, "to": ends}}},
            ]},
        ]})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    timing = client.get("/demo/api/config").json()["story_timing"]
    hub = client.get("/demo/api/hub").json()
    assert timing["guest_window_before_min"] == {"normal": 30, "demo": 1}
    assert hub["ledger"] == [ledger[0], ledger[1], ledger[4]]
    assert hub["guest_windows"]["ep_9031"]["t_mood#3"] == {"from": safety, "to": ends}

    # Run the same formatter as the card and house timeline without a browser.
    script = """
        import assert from 'node:assert/strict';
        import { readFileSync } from 'node:fs';
        const source = readFileSync(process.argv[1]).toString('base64');
        const { displayTime, storyClock, storyObservedTime, storyPlanTime } =
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
        assert.equal(storyObservedTime('2026-11-20T11:41:41+09:00', story, '손님 도착'), '토 13:59');
        const unconfigured = storyClock(event, starts, ends, null);
        assert.equal(displayTime(storyPlanTime(cleaning, unconfigured)), '토 13:57');
    """
    subprocess.run(
        [node, "--input-type=module", "-e", script, str(demo.DEMO_UI / "story-time.js")],
        input=json.dumps(dict(timing=timing, hub=hub, starts=starts, cleaning=cleaning, safety=safety, fallback=fallback)),
        text=True, check=True,
    )


def test_story_timing_falls_back_when_numbers_file_is_missing(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_NUMBERS_PATH", str(tmp_path / "missing.yaml"))
    assert client.get("/demo/api/config").json()["story_timing"] is None


@pytest.mark.parametrize("fixture_mode", [True, False], ids=["fixture", "real"])
def test_server_proxy_reads_only_contract_routes(client, monkeypatch, fixture_mode):
    expected_headers = {"Authorization": "Bearer t"}
    if fixture_mode:
        monkeypatch.setenv("DEMO_FIXTURE_EPISODE", "ep_9031")
        expected_headers["X-SPIRA-Demo-Client"] = "shell"
    seen = []

    async def fake_get(self, url, **kwargs):
        seen.append((url, kwargs["headers"]))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert client.get("/demo/api/server/v1/episodes/ep_9031/rationale").json() == {"ok": True}
    assert seen == [("http://server.test/v1/episodes/ep_9031/rationale", expected_headers)]
    for path in ("v1/hub/plans", "_fixture/receipts", "v1/cards/nc_1/reactions"):
        assert client.get(f"/demo/api/server/{path}").status_code == 404


@pytest.mark.parametrize("status", [404, 405, 501, 503])
def test_clock_proxy_preserves_non_json_error_status(client, monkeypatch, status):
    async def fake_get(self, url, params, headers):
        assert url.endswith("/v1/demo/clock")
        return httpx.Response(status, text="Clock unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    response = client.get("/demo/api/server/v1/demo/clock")
    assert response.status_code == status


def test_real_clock_next_preserves_absent_route_without_falling_back(client, monkeypatch):
    async def fake_post(self, url, *, json, params, headers):
        assert url == "http://server.test/v1/demo/clock/next"
        assert params == {"episode_id": "ep_123"}
        assert json == {"over_seconds": 4}
        assert headers == {"Authorization": "Bearer t"}
        return httpx.Response(405, text="Clock unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    response = client.post("/demo/api/clock/next?episode_id=ep_123", json={"over_seconds": 4})
    assert response.status_code == 405
    assert response.text == "Clock unavailable"


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
            "ledger": ledger, "waiting": waiting, "task_stories": stories, "events": [], "paused": False,
        })

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert client.get("/demo/api/hub?path=/commands").json() == {
        "ledger": ledger, "guest_windows": {},
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
    assert client.get("/demo/api/hub").json() == {
        "ledger": [], "guest_windows": {}, "plan_actions": {},
    }
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
    assert "story:" not in scenes
    assert "30分" not in scenes
    for stage in ("extract", "context", "intent", "tasks", "plan"):
        assert f'"id": "{stage}"' in scenes


def test_recording_writes_json_and_the_presenter_can_label_and_replay_it(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_RECORDINGS_DIR", str(tmp_path))
    first, second = "f" * 32, "a" * 32
    endpoint = "/demo/api/recordings"
    times = {"arrived_at": "2026-11-25T01:22:33Z", "story_at": "2026-10-17T05:00:20Z"}
    observations = [
        {"kind": "share", "data": {"sample": "birthday", "images": 1}},
        {"kind": "episode", "data": {"episode_id": "ep_9031"}},
        {"kind": "cards", "data": {"cards": []}},
        {"kind": "hub", "data": {"ledger": []}},
        {"kind": "clock", "data": {"version": 1}},
        {"kind": "moments", "data": [{"id": "guest_arrived"}]},
        {"kind": "house", "data": {"scene": "guests"}},
        {"kind": "snapshot", "data": {"devices": []}},
        {"kind": "reaction", "data": {"reaction": "line_off", "task_id": "t_oven#4"}},
        {"kind": "rationale", "data": {"observations": [{"verdict": "match"}]}},
        {"kind": "memory", "data": {"intents": []}},
        {"kind": "finish", "data": {"stage": "record"}},
    ]
    batch = {"episode_id": "ep_9031", "household_id": "h_042", "offset": 0,
             "entries": [{**entry, **times} for entry in observations]}
    for recording_id in (first, second):
        path = f"{endpoint}/{recording_id}"
        assert client.post(path, json=batch).json() == {"offset": len(observations)}
        assert client.post(path, json=batch).json() == {"offset": len(observations)}
        assert client.post(path, json={**batch, "offset": 200}).status_code == 409
    on_disk = json.loads((tmp_path / f"{first}.json").read_text())
    assert [{key: v for key, v in entry.items() if key != "read"} for entry in on_disk["entries"]] == batch["entries"]
    assert on_disk["complete"]
    assert [row["id"] for row in client.get(endpoint).json()] == [second, first]
    assert client.patch(f"{endpoint}/{first}", json={"name": "생일 리허설", "starred": True}).status_code == 204
    index = client.get(endpoint).json()
    assert [row["id"] for row in index] == [first, second]
    assert index[0]["name"] == "생일 리허설"
    assert client.get(f"{endpoint}/{first}").json()["entries"] == on_disk["entries"]
    legacy = client.get("/demo?episode=ep_9031&replay=1&dwell=2&owners=1", follow_redirects=False)
    assert legacy.status_code == 307
    assert legacy.headers["location"] == f"/demo?recording={first}&owners=1"
    assert "시연 녹화" in client.get("/demo?recordings").text

def test_server_read_turns_upstream_timeout_into_retryable_status(client, monkeypatch):
    async def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("Timed out")

    monkeypatch.setattr(httpx.AsyncClient, "get", timeout)
    assert client.get("/demo/api/server/v1/episodes/ep_9031").status_code == 504


def test_tagger_is_off_and_does_not_call_the_model(client, monkeypatch):
    episode = "ep_9031"
    rationale = json.loads((Path(__file__).resolve().parents[2] / f"contracts/fixtures/{episode}/rationale.json").read_text())
    calls = []

    async def fake_get(self, url, **options):
        return httpx.Response(200, json=rationale)

    async def unexpected_model(*args):
        calls.append(args)
        return {"tags": []}

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(tagger, "codex_request", unexpected_model)
    with TestClient(demo.create_app()) as disabled:
        assert disabled.get(f"/demo/api/server/v1/episodes/{episode}/rationale").status_code == 200
        assert disabled.get("/demo/tags", params={"episode": episode}).json() == {"ready": False, "tags": []}
    assert calls == []


def test_tagger_calls_once_on_complete_rationale_and_saves_tags_after_recording_finishes(client, monkeypatch):
    episode = "ep_9031"
    fixture = Path(__file__).resolve().parents[2] / "contracts/fixtures" / episode
    rationale = json.loads((fixture / "rationale.json").read_text())
    reading = {**rationale, "tasks": [], "item_tasks": []}
    current = reading
    calls = []
    started, release = Event(), Event()

    async def fake_get(self, url, **options):
        return httpx.Response(200, json=current)

    async def fake_model(schema, prompt):
        rows = json.loads(prompt.split("Source rows: ", 1)[1])
        calls.append(rows)
        started.set()
        assert await asyncio.to_thread(release.wait, 2)
        line = next(row for row in rows if row["kind"] == "line")
        return {"tags": [{"id": line["id"], "short": "거실 청소", "action": "clean"}]}

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr(tagger, "codex_request", fake_model)
    monkeypatch.setenv("DEMO_TAGGER", "codex")
    monkeypatch.setenv("DEMO_FIXTURE_EPISODE", episode)

    run_id = "a" * 32
    headers = {"X-SPIRA-Demo-Run": run_id}
    read_path = f"/demo/api/server/v1/episodes/{episode}/rationale"
    record_path = f"/demo/api/recordings/{run_id}"
    unavailable = {"ready": False, "tags": []}
    batch = {"episode_id": episode, "household_id": "h_042", "offset": 0, "demo_path": "plan", "entries": [
        {"kind": "finish", "data": {"stage": "plan"}, "arrived_at": "2026-11-25T01:22:33Z", "story_at": None},
    ]}
    with TestClient(demo.create_app()) as enabled:
        try:
            assert enabled.get(read_path, headers=headers).status_code == 200
            assert enabled.get(f"/demo/tags?episode={episode}", headers=headers).json() == unavailable
            assert not started.is_set()
            current = rationale
            assert enabled.get(read_path, headers=headers).json() == rationale
            assert started.wait(2)
            assert len(calls[0]) == 15
            for _ in range(4):
                assert enabled.get(read_path, headers=headers).status_code == 200
            assert enabled.get(f"/demo/tags?episode={episode}", headers=headers).json() == unavailable
            assert enabled.post(record_path, json=batch).json() == {"offset": 1}
            assert enabled.get(record_path).json()["complete"] is True
        finally:
            release.set()
        deadline = monotonic() + 2
        while monotonic() < deadline:
            response = enabled.get(f"/demo/tags?episode={episode}", headers=headers).json()
            if response["ready"]:
                break
            sleep(0.005)
        expected = [{"kind": "line", "ref": rationale["tasks"][0]["task_id"], "text": rationale["tasks"][0]["line"],
                     "tag": {"short": "거실 청소", "action": "clean"}}]
        assert response == {"ready": True, "tags": expected}
        assert enabled.get(f"/demo/tags?episode={episode}").json() == response
        assert enabled.get(f"/demo/tags?episode={episode}", headers={"X-SPIRA-Demo-Run": "b" * 32}).json() == unavailable
        saved = enabled.get(record_path).json()
        assert saved["tags"]["data"] == expected
        assert saved["tags"]["arrived_at"]
        assert saved["demo_path"] == "plan"
        assert enabled.get("/demo/api/config", headers={"X-SPIRA-Demo-Episode": episode}).json()["demo_path"] == "plan"
        assert len(calls) == 1

    # A new app has no in-memory run. Opening saved playback and the old read-only
    # rehearsal link must not start a model request.
    with TestClient(demo.create_app()) as replay:
        assert replay.get(f"/demo?recording={run_id}").status_code == 200
        assert replay.get(record_path).json()["tags"]["data"] == expected
        assert replay.get(read_path, headers={"X-SPIRA-Demo-Replay": "1"}).status_code == 200
        assert replay.get(f"/demo/tags?episode={episode}").json() == unavailable
        assert len(calls) == 1
