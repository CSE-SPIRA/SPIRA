"""Shared build and serving commands for the fixture App preview."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


APP = Path(__file__).resolve().parents[1]
APP_TOKEN = "demo"
EPISODE = "ep_9031"
LOOPBACK = "127.0.0.1"
FLUTTER_REQUIRED = "앱 미리보기는 Flutter가 필요합니다 (`--app-web DIR`로 미리 빌드한 것을 쓸 수 있어요)"
BUILD_INPUTS = (
    "app/.metadata", "app/lib", "app/web", "app/assets",
    "app/pubspec.yaml", "app/pubspec.lock", "design/fonts",
)


def origin(port):
    return f"http://{LOOPBACK}:{port}"


def fixture_defines(proxy_port, household, key):
    return {
        "SPIRA_BASE_URL": origin(proxy_port),
        "SPIRA_HUB_URL": origin(proxy_port),
        "SPIRA_HOUSEHOLD_ID": household,
        "SPIRA_PEER": "fixture",
        "SPIRA_FIXTURE_APP_TOKEN": APP_TOKEN,
        "SPIRA_FIXTURE_HOME_KEY": key,
    }


def define_flags(defines):
    return [f"--dart-define={name}={value}" for name, value in defines.items()]


def proxy_command(fixture, hub, proxy_port, web_port):
    return [
        sys.executable, str(APP / "scripts/browser_demo_proxy.py"),
        f"--fixture={fixture}", f"--hub={hub}", f"--port={proxy_port}", f"--web-port={web_port}",
    ]


def web_command(web, port):
    return [
        sys.executable, "-m", "http.server", str(port), "--bind", LOOPBACK,
        "--directory", str(web),
    ]


def cache_root():
    base = os.getenv("XDG_CACHE_HOME")
    if not base:
        base = Path.home() / ("Library/Caches" if sys.platform == "darwin" else ".cache")
    return Path(base) / "spira-demo/app-web"


def temporary_root():
    path = Path("/private/tmp")
    return path if path.is_dir() else Path(tempfile.gettempdir())


def cache_key(defines, root):
    digest = hashlib.sha256(json.dumps([1, defines], sort_keys=True).encode())
    for relative in BUILD_INPUTS:
        source = root / relative
        files = sorted(source.rglob("*")) if source.is_dir() else [source]
        for path in files:
            if path.is_file():
                digest.update(path.relative_to(root).as_posix().encode() + b"\0")
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def valid_web(path):
    return (path / "index.html").is_file() and (path / "flutter_bootstrap.js").is_file()


def cached_web(defines, build):
    """Return (web directory or None, cache hit), invoking build(command, cwd) on a miss."""
    key = cache_key(defines, APP.parent)
    cache = cache_root()
    web = cache / key
    if valid_web(web):
        return web, True
    flutter = shutil.which("flutter")
    if flutter is None:
        return None, False

    cache.mkdir(parents=True, exist_ok=True)
    with (cache / f"{key}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if valid_web(web):
            return web, True
        with tempfile.TemporaryDirectory(prefix="spira-app-build-", dir=temporary_root()) as workspace:
            root = Path(workspace)
            for relative in BUILD_INPUTS:
                source, target = APP.parent / relative, root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
            if cache_key(defines, root) != key:
                raise RuntimeError("App source changed while preparing the build. Run the command again.")
            output = root / "web"
            result = build(
                [flutter, "build", "web", f"--output={output}", *define_flags(defines)],
                root / "app",
            )
            if result or not valid_web(output):
                raise RuntimeError(f"Flutter web build failed (exit status {result}).")
            # Publish on the cache filesystem so readers only see complete builds.
            with tempfile.TemporaryDirectory(prefix=".build-", dir=cache) as staging:
                staged_web = Path(staging) / "web"
                shutil.copytree(output, staged_web)
                if web.exists():
                    shutil.rmtree(web)
                staged_web.rename(web)
        return web, False
