import os
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from app.scripts import browser_demo_web as web
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
