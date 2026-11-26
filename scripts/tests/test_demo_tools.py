import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection, IncompleteRead, RemoteDisconnected
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from threading import Barrier, Thread
import time
import urllib.request
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.scripts import browser_demo_web as web
from scripts.demo_app_proxy import create_app
from scripts.demo_fixture import create_demo_fixture
from scripts.demo_start import guest_window, window_status
from scripts.demo_up import cached_app, choose_ports


ROOT = Path(__file__).resolve().parents[2]


def test_web_cache_reuses_build_and_tracks_source_and_defines(tmp_path, monkeypatch):
    source = tmp_path / "checkout"
    dart = source / "app/lib/main.dart"
    dart.parent.mkdir(parents=True)
    dart.write_text("initial source")
    flutter = tmp_path / "bin/flutter"
    flutter.parent.mkdir()
    flutter.touch(mode=0o755)
    git = shutil.which("git")
    assert git
    (flutter.parent / "git").symlink_to(git)
    tree = subprocess.check_output([git, "rev-parse", "HEAD:app"], cwd=ROOT, text=True).strip()
    monkeypatch.setenv("PATH", str(flutter.parent))
    monkeypatch.setenv("DEMO_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(web, "temporary_root", lambda: tmp_path)
    monkeypatch.setattr(web, "APP", source / "app")
    monkeypatch.setattr(web, "BUILD_INPUTS", ("app/lib",))
    defines = {"SPIRA_BASE_URL": "http://127.0.0.1:8941"}
    builds = []

    def build(command, cwd):
        assert command[:3] == [str(flutter), "build", "web"]
        assert (cwd / "lib/main.dart").read_text() == dart.read_text()
        output = next(Path(arg.partition("=")[2]) for arg in command if arg.startswith("--output="))
        output.mkdir()
        for name in ("index.html", "flutter_bootstrap.js"):
            (output / name).touch()
        builds.append(output)
        return 0

    original_key = web.cache_key(defines, source)
    path, hit = cached_app(defines, build)
    assert path.name == original_key
    assert path.is_relative_to(tmp_path / "state")
    assert tree in path.parts
    assert not hit
    assert cached_app(defines, build) == (path, True)
    assert len(builds) == 1

    dart.write_text("updated source")
    updated, hit = cached_app(defines, build)
    assert not hit
    assert updated != path
    assert web.cache_key({"SPIRA_BASE_URL": "http://127.0.0.1:8948"}, source) != updated.name
    assert len(builds) == 2

    flutter.unlink()
    assert cached_app(defines, build) == (updated, True)


def test_guest_window_from_completed_hub_task():
    opens = datetime(2026, 11, 21, 9, tzinfo=UTC)
    closes = opens + timedelta(minutes=10)
    trigger = {"event": "guest_arrived", "window": {"from": opens.isoformat(), "to": closes.isoformat()}}
    window = guest_window({"waiting": [], "task_stories": [{"steps": [{"trigger": trigger}]}]})
    assert window == (opens, closes)
    assert window_status(window, opens - timedelta(seconds=1)) == {"status": "pending"}
    assert window_status(window, opens + timedelta(seconds=61)) == {"status": "open", "minutes": 9}
    assert window_status(window, closes + timedelta(seconds=1)) == {"status": "passed"}


def test_demo_fixture_keeps_clock_state_on_restart(tmp_path):
    route = "/v1/demo/clock"
    checkpoint = tmp_path / "fixture.state"
    initial = "2026-10-15T20:59:08+09:00"
    with TestClient(create_demo_fixture("ep_9031", checkpoint, True)) as client:
        before = client.post(route, json={"set_to": initial}).json()
    with TestClient(create_demo_fixture("ep_9031", checkpoint, True)) as client:
        after = client.get(route).json()
        cards = client.get("/v1/households/h_042/cards", headers={"Authorization": "Bearer demo"}).json()
    assert {key: value for key, value in after.items() if key != "now"} == {
        key: value for key, value in before.items() if key != "now"
    }
    assert datetime.fromisoformat(after["now"]) >= datetime.fromisoformat(before["now"])
    assert datetime.fromisoformat(cards["server_time"]) >= datetime.fromisoformat(after["now"])


def test_real_launcher_requires_environment_keys(monkeypatch, capsys):
    from scripts import demo_up

    monkeypatch.delenv("SPIRA_HUB_KEY", raising=False)
    monkeypatch.delenv("SPIRA_APP_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", ["demo-up", "--server", "http://127.0.0.1:1"])
    assert demo_up.main() == 1
    guide = capsys.readouterr().err
    for word in ("POST /v1/households", "APP_DEMO_TOKEN", "SPIRA_APP_TOKEN", "hub_api_key", "SPIRA_HUB_KEY"):
        assert word in guide


def test_real_launcher_checks_reachability_before_running(monkeypatch, capsys):
    from scripts import demo_up

    monkeypatch.setenv("SPIRA_HUB_KEY", "test-hub-key")
    monkeypatch.setenv("SPIRA_APP_TOKEN", "test-app-token")
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{reserved.getsockname()[1]}"
        monkeypatch.setattr(sys, "argv", ["demo-up", "--server", url])
        assert demo_up.main() == 1
    assert f"Cannot reach Server at {url}/health" in capsys.readouterr().err


def test_real_app_proxy_uses_backend_credentials(monkeypatch):
    origin = "http://127.0.0.1:8700"
    for name, value in {
        "SPIRA_SERVER_URL": "http://server.test",
        "SPIRA_HOUSEHOLD": "h_123",
        "SPIRA_WEB_ORIGIN": origin,
        "SPIRA_APP_TOKEN": "test-app-token",
    }.items():
        monkeypatch.setenv(name, value)
    calls = []

    async def upstream(self, method, url, **kwargs):
        calls.append((url, kwargs["headers"], dict(kwargs["params"])))
        return httpx.Response(404, json={"code": "not_found"})

    monkeypatch.setattr(httpx.AsyncClient, "request", upstream)
    with TestClient(create_app()) as client:
        headers = {"Origin": origin, "Authorization": "Bearer browser", "X-API-Key": "browser"}
        assert client.get("/home/onboarding/devices", headers=headers).status_code == 404
        assert client.get("/v1/households/h_123/cards?since=2026-10-15", headers=headers).status_code == 404
        assert client.get("/v1/households/h_042/cards", headers=headers).status_code == 404
        assert client.get("/_fixture/control", headers=headers).status_code == 404
        assert client.get("/v1/households/h_123/cards").status_code == 403
    assert calls == [
        ("http://server.test/v1/households/h_123/cards",
         {"Accept": "application/json", "Authorization": "Bearer test-app-token"}, {"since": "2026-10-15"}),
    ]


def test_stack_starts_without_flutter(tmp_path):
    broker = shutil.which("mosquitto")
    if broker is None:
        pytest.skip("Mosquitto is required for the live launcher test")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "mosquitto").symlink_to(Path(broker).resolve())
    env = {
        **os.environ,
        "PATH": str(binaries),
        "DEMO_STATE_ROOT": str(tmp_path / "state"),
        "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "contracts/generated/python"))),
    }
    with ExitStack() as stack:
        listeners = [stack.enter_context(socket.socket()) for _ in range(4)]
        for listener in listeners:
            listener.bind(("127.0.0.1", 0))
        sim, start, proxy, app = [str(listener.getsockname()[1]) for listener in listeners]
    with (tmp_path / "launcher.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/demo_up.py"), "--no-shell",
             "--port", sim, "--start-port", start, "--proxy-port", proxy, "--web-port", app],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                log.seek(0)
                output = log.read()
                if web.FLUTTER_REQUIRED in output or process.poll() is not None:
                    break
                time.sleep(0.1)
            assert web.FLUTTER_REQUIRED in output, output
            assert output.splitlines()[0] == f"시작 페이지: http://127.0.0.1:{start}/"
            assert "(operator / " not in output
            clock_url = next(line.split()[1] for line in output.splitlines() if line.startswith("Clock:"))
            control_url = next(line.split()[1] for line in output.splitlines() if line.startswith("Control:"))
            run_dir = next(line.removeprefix("Logs:").strip() for line in output.splitlines() if line.startswith("Logs:"))
            assert control_url in (Path(run_dir) / "urls.txt").read_text()
            with urllib.request.urlopen(control_url, timeout=5) as response:
                assert "예시 판단, 추론 아님" in response.read().decode()
            arm = urllib.request.Request(
                control_url + "/fault", data=b'{"group":"health","kind":"drop","count":1}',
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(arm, timeout=5) as response:
                assert json.load(response)["faults"][0]["kind"] == "drop"
            connection = HTTPConnection(urlsplit(control_url).netloc, timeout=5)
            try:
                connection.request("GET", "/health")
                with pytest.raises((IncompleteRead, RemoteDisconnected)):
                    connection.getresponse().read()
            finally:
                connection.close()
            with urllib.request.urlopen(clock_url, timeout=5) as response:
                assert json.load(response)["story_at"] == "2026-10-15T20:59:08+09:00"
            with urllib.request.urlopen(f"http://127.0.0.1:{start}/", timeout=5) as response:
                assert response.status == 200
                page = response.read().decode()
                assert "SPIRA 시연" in page
                assert "예시 연출(제품 아님)" not in page
                assert f"http://127.0.0.1:{app}/" not in page
            with urllib.request.urlopen(f"http://127.0.0.1:{sim}/operator", timeout=5) as response:
                assert response.status == 200
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)


def wait_for(probe, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if value := probe():
            return value
        time.sleep(0.1)
    raise AssertionError("Demo condition did not become ready")


@contextmanager
def local_launcher(tmp_path, *options, env=None, app_web=None):
    if shutil.which("mosquitto") is None:
        pytest.skip("Mosquitto is required for the live launcher test")
    ports = choose_ports(dict.fromkeys(("sim", "fixture", "mqtt", "hub", "shell", "start", "proxy", "app"), 0), "127.0.0.1")
    command = [
        sys.executable, str(ROOT / "scripts/demo_up.py"),
        *(["--no-app"] if app_web is None else ["--app-web", str(app_web)]),
        "--proxy-port", str(ports["proxy"]), "--web-port", str(ports["app"]),
        "--port", str(ports["sim"]), "--shell-port", str(ports["shell"]),
        "--start-port", str(ports["start"]), "--peer-ports",
        *(str(ports[name]) for name in ("fixture", "mqtt", "hub")), *options,
    ]
    log_path = tmp_path / "launcher.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(command, cwd=ROOT, env={
            **os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
            "DEMO_STATE_ROOT": str(tmp_path / "state"), **(env or {}),
        }, stdout=log, stderr=subprocess.STDOUT)
        try:
            def ready():
                output = log_path.read_text()
                assert process.poll() is None, output
                if "Ctrl-C to stop." in output:
                    return Path(next(line.split(maxsplit=1)[1] for line in output.splitlines() if line.startswith("Logs:")))

            logs = wait_for(ready)
            urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items()}
            with httpx.Client(timeout=90, trust_env=False) as client:
                yield client, urls, logs
            assert process.poll() is None, log_path.read_text()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=20)


@pytest.mark.parametrize("prebuilt", [False, True], ids=["no-app", "app-web"])
def test_launcher_config_embeds_a_prebuilt_app_or_disables_the_preview(tmp_path, prebuilt):
    web_dir = tmp_path / "web" if prebuilt else None
    if web_dir is not None:
        web_dir.mkdir()
        (web_dir / "index.html").write_text("prebuilt App")
    with local_launcher(tmp_path, app_web=web_dir) as (client, urls, logs):
        config = client.get(urls["shell"] + "/demo/api/config").raise_for_status().json()
        assert not (logs / "app-build.log").exists()
        if not prebuilt:
            assert config["app_url"] is None
            assert not (logs / "app-web.log").exists()
            return
        assert config["app_url"] == urls["app"]
        assert client.get(config["app_url"]).raise_for_status().text == "prebuilt App"
        headers = {"Origin": urls["app"], "Authorization": "Bearer demo"}
        cards = "/v1/households/h_042/cards"
        through_proxy = client.get(urls["proxy"] + cards, headers=headers).raise_for_status().json()
        direct = client.get(urls["fixture"] + cards, headers=headers).raise_for_status().json()
        assert through_proxy["cards"] == direct["cards"]
        assert through_proxy["server_time"] <= direct["server_time"]
        accepted = client.post(
            urls["proxy"] + "/v1/orders", headers=headers, data={"household_id": "h_042"},
            files={"images": ("example.png", b"fixture order", "image/png")},
        ).raise_for_status().json()
        episodes = client.get(
            urls["shell"] + "/demo/api/server/v1/households/h_042/episodes",
        ).raise_for_status().json()["episodes"]
        assert episodes[0]["episode_id"] == accepted["episode_id"]


def test_launcher_reset_restarts_fresh_peers_on_same_ports_with_keep(tmp_path):
    with local_launcher(tmp_path, "--keep", "--realistic", "11", "--tagger") as (client, urls, logs):
        shell, fixture, hub, sim = (urls[name] for name in ("shell", "fixture", "hub", "sim"))
        episode_list = f"{fixture}/v1/households/h_042/episodes"
        app_headers = {"Authorization": "Bearer demo"}
        fixture_control = f"{fixture}/_fixture/control/state"
        viewer_url = f"{sim}/sim/viewer?fragment=true"
        reset_url = f"{shell}/demo/api/reset"
        config = client.get(f"{shell}/demo/api/config").raise_for_status().json()
        assert config["fixture"] and config["reset"] and config["tagger"]
        assert "진행자 조작 → 새로 시작" in client.get(urls["start"]).raise_for_status().text
        assert client.post(f"{urls['start']}/reset").status_code == 403
        assert client.get(episode_list, headers=app_headers).raise_for_status().json()["episodes"] == []
        initial_clock = client.get(f"{fixture}/v1/demo/clock").raise_for_status().json()["story_at"]
        initial_world = client.get(f"{sim}/sim/snapshot").raise_for_status().json()
        epoch = initial_world["world_epoch"]
        accepted = client.post(f"{shell}/demo/api/order", data={"sample": "birthday"},
                               files={"images": ("sample.png", b"demo screenshot", "image/png")})
        assert accepted.status_code == 202, accepted.text
        episode = accepted.json()["episode_id"]
        assert client.get(episode_list, headers=app_headers).raise_for_status().json()["episodes"][0]["episode_id"] == episode
        story_at = client.get(f"{fixture}/v1/demo/clock").raise_for_status().json()["story_at"]
        later = datetime.fromisoformat(story_at) + timedelta(hours=1)
        client.post(f"{fixture}/v1/demo/clock", json={"set_to": later.isoformat()}).raise_for_status()

        def world_now():
            return datetime.fromisoformat(client.get(f"{sim}/sim/snapshot").raise_for_status().json()["now"])

        assert wait_for(lambda: later <= world_now() < later + timedelta(minutes=5))
        for action in ("delivery", "guests_arrive"):
            client.post(f"{shell}/demo/api/home/{action}").raise_for_status()
        dirty = client.get(viewer_url).raise_for_status().text
        assert 'data-signal="package"' in dirty and "data-guest-arrival=" in dirty
        assert wait_for(lambda: client.get(f"{hub}/state").raise_for_status().json()["plan_history"])
        shell_log = (logs / "shell.log").read_text()

        barrier = Barrier(2, timeout=5)

        def reset():
            barrier.wait()
            return client.post(reset_url).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: reset(), range(2))) == [204, 409]

        assert client.get(f"{shell}/demo/api/config").raise_for_status().json() == config
        assert (logs / "shell.log").read_text() == shell_log
        assert client.get(episode_list, headers=app_headers).raise_for_status().json()["episodes"] == []
        assert client.get(fixture_control).raise_for_status().json()["realistic_seed"] == 11
        assert client.get(f"{fixture}/v1/demo/clock").raise_for_status().json()["story_at"] == initial_clock
        fresh_hub = client.get(f"{hub}/state").raise_for_status().json()
        assert fresh_hub["plan_history"] == fresh_hub["current_plans"] == fresh_hub["waiting"] == []
        fresh_world = client.get(f"{sim}/sim/snapshot").raise_for_status().json()
        assert fresh_world["world_epoch"] != epoch
        assert datetime.fromisoformat(initial_clock) <= datetime.fromisoformat(fresh_world["now"]) < later
        assert {device["target"]: device["values"] for device in fresh_world["devices"]} == {
            device["target"]: device["values"] for device in initial_world["devices"]
        }
        clean = client.get(viewer_url).raise_for_status().text
        assert 'data-signal="package"' not in clean and "data-guest-arrival=" not in clean


@pytest.mark.parametrize("with_app", [False, True], ids=["no-app", "app-web"])
def test_launcher_reset_in_server_mode_uses_only_local_reset_routes(tmp_path, with_app):
    calls = []

    class Server(BaseHTTPRequestHandler):
        def respond(self):
            path = urlsplit(self.path).path
            calls.append((self.command, path))
            if path == "/v1/households/h_123/episodes" and self.headers.get("Authorization") == "Bearer test-app-token":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"episodes":[],"next_before":null}')
                return
            self.send_response(200 if path == "/health" else 404)
            self.end_headers()

        do_GET = do_POST = do_PUT = do_DELETE = respond

        def log_message(self, *_):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Server) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            keys = {"SPIRA_HUB_KEY": "test-hub-key", "SPIRA_APP_TOKEN": "test-app-token"}
            app_web = tmp_path / "web" if with_app else None
            if app_web is not None:
                app_web.mkdir()
                (app_web / "index.html").write_text("Server App")
            with local_launcher(tmp_path, "--server", url, "--household", "h_123",
                                env=keys, app_web=app_web) as (client, urls, logs):
                shell = urls["shell"]
                config = client.get(f"{shell}/demo/api/config").raise_for_status().json()
                assert config["reset"] and not config["fixture"] and config["household_id"] == "h_123"
                assert config["app_url"] == (urls["app"] if with_app else None)
                episode_feed = "/v1/households/h_123/episodes"
                if with_app:
                    assert client.get(config["app_url"]).raise_for_status().text == "Server App"
                    app_feed = client.get(urls["proxy"] + episode_feed, headers={"Origin": urls["app"]})
                    shell_feed = client.get(shell + "/demo/api/server" + episode_feed)
                    assert app_feed.raise_for_status().json() == shell_feed.raise_for_status().json()
                snapshot_url = f"{urls['sim']}/sim/snapshot"
                before = client.get(snapshot_url).raise_for_status().json()
                recording_url = f"{shell}/demo/api/recordings/{'a' * 32}"
                client.post(recording_url, json={
                    "episode_id": "ep_9031", "household_id": "h_123", "offset": 0,
                    "entries": [{"kind": "presenter", "data": {"action": "reset"},
                                 "arrived_at": datetime.now(UTC).isoformat(), "story_at": None}],
                }).raise_for_status()
                saved = client.get(recording_url).raise_for_status().json()
                assert client.post(f"{shell}/demo/api/reset").status_code == 204
                after = client.get(snapshot_url).raise_for_status().json()
                assert after["world_epoch"] != before["world_epoch"] and after["household_id"] == "h_123"
                assert client.get(recording_url).raise_for_status().json() == saved
                assert not (logs / "fixture.log").exists()
                # The Hub resumes its ordinary plan polling. The launcher makes its
                # Server health/clock probes once, at initial startup only.
                plan_poll = ("GET", "/v1/hub/plans")
                assert plan_poll in calls
                initial = [("GET", "/health"), ("GET", "/v1/demo/clock")]
                if with_app:
                    initial.extend([("GET", "/health"), ("GET", episode_feed), ("GET", episode_feed)])
                assert [call for call in calls if call != plan_poll] == initial
        finally:
            server.shutdown()
            thread.join()
