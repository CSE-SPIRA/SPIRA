"""Build and install a debug Android App for the loopback demo stack."""

import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.scripts.browser_demo_web import BUILD_INPUTS, define_flags


APK_INPUTS = (*[path for path in BUILD_INPUTS if path != "app/web"], "app/android")
GRADLE_GENERATED = (
    ".gradle", ".kotlin", "build", "local.properties", "key.properties",
    "gradlew", "gradlew.bat", "gradle-wrapper.jar",
)
APK_OUTPUT = "app/build/app/outputs/flutter-apk/app-debug.apk"


def source_files(root):
    for relative in APK_INPUTS:
        source = root / relative
        if not source.is_dir():
            yield source
            continue
        ignored = GRADLE_GENERATED if relative == "app/android" else ()
        for directory, subdirectories, names in os.walk(source):
            subdirectories[:] = sorted(name for name in subdirectories if name not in ignored)
            for name in sorted(name for name in names if name not in ignored):
                yield Path(directory) / name


def apk_key(source, defines):
    digest = hashlib.sha256(json.dumps([1, defines], sort_keys=True).encode())
    for path in source_files(source):
        digest.update(path.relative_to(source).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def cached_apk(source, cache, defines, build):
    key = apk_key(source, defines)
    directory = cache / "app-android" / key
    apk = directory / "app-debug.apk"
    if apk.is_file():
        return apk, True
    flutter = shutil.which("flutter")
    if flutter is None:
        raise RuntimeError("Flutter is required to build the debug APK.")

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if apk.is_file():
            return apk, True
        with tempfile.TemporaryDirectory(prefix=".build-", dir=directory) as workspace:
            root = Path(workspace)
            for file in source_files(source):
                target = root / file.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
            if apk_key(root, defines) != key:
                raise RuntimeError("App source changed while preparing the APK. Run the command again.")
            result = build([flutter, "build", "apk", "--debug", *define_flags(defines)], root / "app")
            output = root / APK_OUTPUT
            if result or not output.is_file() or not output.stat().st_size:
                raise RuntimeError(f"Flutter APK build failed (exit status {result}).")
            output.replace(apk)
    return apk, False


def application_id(source):
    gradle = (source / "app/android/app/build.gradle.kts").read_text(encoding="utf-8")
    if match := re.search(r'^\s*applicationId\s*=\s*"([a-zA-Z0-9_.]+)"', gradle, re.MULTILINE):
        return match[1]
    raise RuntimeError("Could not read the App's Android application ID.")


def install_phone(apk, port, app_id):
    reverse = ["reverse", f"tcp:{port}", f"tcp:{port}"]
    install = ["install", "-r", str(apk)]
    reset = ["shell", "pm", "clear", app_id]
    adb = shutil.which("adb")
    installed = False
    manual = ["adb"]
    if adb:
        try:
            status = subprocess.run([adb, "devices"], capture_output=True, text=True, check=True)
            listing = status.stdout.partition("List of devices attached")[2]
            rows = [line.split() for line in listing.splitlines() if line.strip()]
            if len(rows) > 1:
                manual += ["-s", "SERIAL"]
                print("Several ADB devices are attached. Replace SERIAL with the selected device ID.")
            if len(rows) == 1 and rows[0][1:2] == ["device"]:
                device = [adb, "-s", rows[0][0]]
                subprocess.run([*device, *reverse], check=True)
                subprocess.run([*device, *install], check=True)
                print(f"Installed on {rows[0][0]}. Open SPIRA on the phone.")
                installed = True
        except (OSError, subprocess.CalledProcessError):
            print("ADB could not install the APK automatically.")
    if not installed:
        for command in (reverse, install):
            print(shlex.join([*manual, *command]))
    print(f"Reset App data with `{shlex.join([*manual, *reset])}`.")
