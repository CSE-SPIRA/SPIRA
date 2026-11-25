import json
import os
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection, IncompleteRead, RemoteDisconnected
from pathlib import Path
import shutil
import socket
import subprocess
import sys
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


ROOT = Path(__file__).resolve().parents[2]


def test_web_cache_reuses_build_and_tracks_source_and_defines(tmp_path, monkeypatch):
    source = tmp_path / "checkout"
    dart = source / "app/lib/main.dart"
    dart.parent.mkdir(parents=True)
    dart.write_text("initial source")
    flutter = tmp_path / "bin/flutter"
    flutter.parent.mkdir()
    flutter.touch(mode=0o755)
    monkeypatch.setenv("PATH", str(flutter.parent))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(web, "APP", source / "app")
    monkeypatch.setattr(web, "BUILD_INPUTS", ("app/lib",))
    defines = {"SPIRA_BASE_URL": "http://127.0.0.1:8941"}
    builds = []

    def build(command, cwd):
        assert command[0] == str(flutter)
        assert (cwd / "lib/main.dart").read_text() == dart.read_text()
        output = next(Path(arg.partition("=")[2]) for arg in command if arg.startswith("--output="))
        output.mkdir()
        for name in ("index.html", "flutter_bootstrap.js"):
            (output / name).touch()
        builds.append(output)
        return 0

    original_key = web.cache_key(defines, source)
    path, hit = web.cached_web(defines, build)
    assert path.name == original_key
    assert not hit
    assert web.cached_web(defines, build) == (path, True)
    assert len(builds) == 1

    dart.write_text("updated source")
    updated, hit = web.cached_web(defines, build)
    assert not hit
    assert updated != path
    assert web.cache_key({"SPIRA_BASE_URL": "http://127.0.0.1:8948"}, source) != updated.name
    assert len(builds) == 2

    flutter.unlink()
    assert web.cached_web(defines, build) == (updated, True)


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
        "SPIRA_HUB_URL": "http://hub.test",
        "SPIRA_HOUSEHOLD": "h_123",
        "SPIRA_WEB_ORIGIN": origin,
        "SPIRA_HUB_KEY": "test-hub-key",
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
        ("http://hub.test/home/onboarding/devices", {"Accept": "application/json", "X-API-Key": "test-hub-key"}, {}),
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
        "XDG_CACHE_HOME": str(tmp_path / "empty-cache"),
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
