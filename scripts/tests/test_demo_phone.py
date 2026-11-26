"""Launcher APK builds and installation with stand-ins for Flutter and ADB."""

import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import pytest

from scripts import demo_phone
from scripts.tests.test_demo_tools import local_launcher


FAKE_TOOL = r'''
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["PHONE_TEST_TOOLS_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if name == "adb" and args == ["devices"]:
    print("List of devices attached")
    print(os.environ["PHONE_TEST_DEVICES"])
if name == "flutter" and args[:2] == ["build", "apk"]:
    assert Path("android/app/build.gradle.kts").is_file()
    output = Path("build/app/outputs/flutter-apk/app-debug.apk")
    output.parent.mkdir(parents=True)
    output.write_bytes(b"debug APK")
if name == "flutter" and args[:2] == ["build", "web"]:
    output = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--output=")))
    output.mkdir()
    for file in ("index.html", "flutter_bootstrap.js"):
        (output / file).touch()
'''


@pytest.mark.parametrize(("devices", "first_run"), [
    (["serial-a\tdevice"], False), ([], False), (["a\tdevice", "b\tdevice"], False), ([], True),
], ids=["one-device", "no-device", "multiple-devices", "first-run"])
def test_launcher_phone_build_and_adb(tmp_path, devices, first_run):
    tools_log = tmp_path / "tools.jsonl"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("adb", "flutter"):
        tool = bin_dir / name
        tool.write_text(f"#!{sys.executable}\n" + FAKE_TOOL)
        tool.chmod(0o700)
    env = {
        "PATH": os.pathsep.join((str(bin_dir), os.environ["PATH"])),
        "PHONE_TEST_TOOLS_LOG": str(tools_log),
        "PHONE_TEST_DEVICES": "\n".join(devices),
    }
    options = ["--phone", *(["--first-run"] if first_run else [])]
    one_device = len(devices) == 1
    with local_launcher(tmp_path, *options, env=env, build_web=one_device) as (client, urls, _):
        proxy = urls["proxy"]
        port = urlsplit(proxy).port
        calls = [json.loads(line) for line in tools_log.read_text().splitlines()]
        flags = [f"--dart-define=SPIRA_BASE_URL={proxy}", "--dart-define=SPIRA_PEER=fixture",
                 "--dart-define=SPIRA_FIXTURE_APP_TOKEN=demo",
                 "--dart-define=SPIRA_FIRST_RUN=1" if first_run else "--dart-define=SPIRA_HOUSEHOLD_ID=h_042"]
        apk_build, = [call for call in calls if call[:3] == ["flutter", "build", "apk"]]
        assert "--debug" in apk_build
        assert sorted(flag for flag in apk_build if flag.startswith("--dart-define=")) == sorted(flags)
        if one_device:
            web_build, = [call for call in calls if call[:3] == ["flutter", "build", "web"]]
            assert sorted(flag for flag in web_build if flag.startswith("--dart-define=")) == sorted(flags)

        output = (tmp_path / "launcher.log").read_text()
        apk = Path(next(line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("Phone APK")))
        assert apk.read_bytes() == b"debug APK"
        reverse = ["reverse", f"tcp:{port}", f"tcp:{port}"]
        install = ["install", "-r", str(apk)]
        adb = [call for call in calls if call[0] == "adb"]
        manual = "adb -s SERIAL" if len(devices) > 1 else "adb"
        if one_device:
            assert adb == [["adb", "devices"], ["adb", "-s", "serial-a", *reverse],
                           ["adb", "-s", "serial-a", *install]]
        else:
            assert adb == [["adb", "devices"]]
            assert f"{manual} reverse tcp:{port} tcp:{port}" in output
            assert f"{manual} install -r {apk}" in output
        assert f"{manual} shell pm clear org.cse_spira.spira_app" in output

        headers = {"Authorization": "Bearer demo"}
        assert client.get(f"{proxy}/v1/households/h_042/cards", headers=headers).status_code == 200
        assert client.get(f"{proxy}/v1/households/h_042/cards").status_code == 403
        if first_run:
            created = client.post(f"{proxy}/v1/households", headers=headers, json={"household_types": []})
            assert created.status_code == 201 and created.json()["household_id"] == "h_042"


def test_phone_cache_reuses_apk_and_tracks_android_source_and_defines(tmp_path, monkeypatch):
    source = tmp_path / "source"
    android = source / "app/android/app/build.gradle.kts"
    android.parent.mkdir(parents=True)
    android.write_text('applicationId = "org.cse_spira.spira_app"')
    cache = tmp_path / "cache"
    monkeypatch.setattr(demo_phone, "APK_INPUTS", ("app/android",))
    monkeypatch.setattr(demo_phone.shutil, "which", lambda name: "/fake/flutter")
    builds = []

    def build(command, cwd):
        assert command[:4] == ["/fake/flutter", "build", "apk", "--debug"]
        assert (cwd / "android/app/build.gradle.kts").read_bytes() == android.read_bytes()
        assert not (cwd / "android/local.properties").exists()
        output = cwd.parent / demo_phone.APK_OUTPUT
        output.parent.mkdir(parents=True)
        output.write_bytes(b"APK")
        builds.append(command)
        return 0

    defines = {"SPIRA_BASE_URL": "http://127.0.0.1:8731", "SPIRA_PEER": "fixture"}
    apk, hit = demo_phone.cached_apk(source, cache, defines, build)
    assert not hit and apk.is_file()
    (source / "app/android/local.properties").write_text("generated file")
    assert demo_phone.cached_apk(source, cache, defines, build) == (apk, True)
    first_run, hit = demo_phone.cached_apk(source, cache, {**defines, "SPIRA_FIRST_RUN": "1"}, build)
    assert not hit and first_run != apk
    android.write_text('applicationId = "org.cse_spira.test"')
    updated, hit = demo_phone.cached_apk(source, cache, defines, build)
    assert not hit and updated not in (apk, first_run) and len(builds) == 3
    monkeypatch.setattr(demo_phone.shutil, "which", lambda name: None)
    assert demo_phone.cached_apk(source, cache, defines, build) == (updated, True)
