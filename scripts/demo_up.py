"""Start the demo stack with a fixture or an existing Server.

Run through scripts/demo-up for the Python environment. Ctrl-C stops everything.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import Future
from contextlib import ExitStack, suppress
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path
from queue import Empty, Queue
from threading import Lock
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from spira_contracts.episode import Episode
from spira_contracts.household_created import HouseholdCreated

from app.scripts.browser_demo_web import (
    APP_TOKEN, FLUTTER_REQUIRED, cached_web, fixture_defines, origin, proxy_command, temporary_root,
    web_command,
)
from scripts.demo_start import guest_window, serve_start_page

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts/generated/python"
HOUSEHOLD = "h_042"
PROFILES = {"ep_9031": "ep_9031.json"}
KEY_GUIDE = """서버 접속에 SPIRA_HUB_KEY와 SPIRA_APP_TOKEN 환경 변수가 필요해요.
서버의 APP_DEMO_TOKEN을 SPIRA_APP_TOKEN으로 설정하세요.
이 토큰을 Bearer로 보내 POST /v1/households에 {"household_types": []}를 등록하세요.
응답의 hub_api_key를 SPIRA_HUB_KEY로 설정하고 household_id를 --household에 넣으세요."""


def write_demo_installation(path, household):
    base = ROOT / "hub/installation.example.json"
    additions = Path(__file__).with_name("demo-devices.json")
    installation = json.loads(base.read_text(encoding="utf-8"))
    demo = json.loads(additions.read_text(encoding="utf-8"))
    installation["devices"]["household_id"] = household
    installation["devices"]["devices"].extend(demo["devices"])
    installation["bindings"].update(demo["bindings"])
    path.write_text(json.dumps(installation, ensure_ascii=False), encoding="utf-8")


def choose_ports(requests, sim_host):
    with ExitStack() as stack:
        ports = {}
        for name, requested in sorted(requests.items(), key=lambda item: item[1] == 0):
            listener = stack.enter_context(socket.socket())
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((sim_host if name == "sim" else "127.0.0.1", requested))
            listener.listen()
            ports[name] = listener.getsockname()[1]
    return ports


def read_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def reachable(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status == 200


def state_root():
    path = Path(os.environ.get("DEMO_STATE_ROOT", temporary_root()))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def run_directory(port, episode, server=None, household=HOUSEHOLD):
    temp = state_root()
    base = f"{ROOT}:{port}:{episode}"
    if server:
        base += f":{server}:{household}"
    identity = hashlib.sha256(base.encode()).hexdigest()[:16]
    path = temp / f"spira-demo-{os.getuid()}-{identity}"
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        sys.exit(f"demo-up state directory must be private and owned by the current user: {path}")
    return path


def server_url(value):
    try:
        url = urlsplit(value)
        if (url.scheme in {"http", "https"} and url.hostname and "@" not in url.netloc
                and url.port != 0 and not re.search(r"[?#\s]", value)):
            return value.rstrip("/")
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Use an HTTP(S) Server URL without credentials, a query or a fragment")


def check_server(server):
    try:
        response = httpx.get(f"{server}/health", timeout=5, trust_env=False)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise RuntimeError(f"Server is not ready at {server}/health (HTTP {error.response.status_code})") from None
    except httpx.RequestError:
        raise RuntimeError(f"Cannot reach Server at {server}/health") from None


def server_clock(server):
    url = f"{server}/v1/demo/clock"
    try:
        response = httpx.get(url, timeout=3, trust_env=False)
        response.raise_for_status()
        datetime.fromisoformat(response.json()["now"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    return url


def cached_app(defines, build):
    # The App builder also hashes its working Flutter inputs, including uncommitted source changes.
    try:
        tree = subprocess.check_output(
            ["git", "rev-parse", "HEAD:app"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        tree = "working-tree"

    cache = state_root() / f"spira-app-cache-{os.getuid()}"
    cache.mkdir(mode=0o700, exist_ok=True)
    info = cache.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError(f"App cache directory must be private and owned by the current user: {cache}")

    # Use the App builder's cache-location entry point for this call.
    previous_cache = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = str(cache / tree)
    try:
        return cached_web(defines, build)
    finally:
        if previous_cache is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = previous_cache


def export_app(destination, defines):
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise RuntimeError("--export-app requires a new or empty directory")
    web, hit = cached_app(defines, lambda command, cwd: subprocess.call(command, cwd=cwd))
    if web is None:
        raise RuntimeError(FLUTTER_REQUIRED)
    shutil.copytree(web, destination, dirs_exist_ok=True)
    source = "cache hit" if hit else "built"
    print(f"App build: {source}\nApp export: {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=server_url, metavar="URL", help="Use an existing Server")
    parser.add_argument("--household", default=HOUSEHOLD, help=f"Household ID (default {HOUSEHOLD})")
    parser.add_argument("--port", type=int, default=8730, help="Simulator port (default 8730)")
    parser.add_argument("--sim-lan-ip", type=IPv4Address, metavar="IP",
                        help="Expose the Simulator on the demo LAN and print its operator URL at IP")
    parser.add_argument("--start-port", type=int, default=8729,
                        help="Start page port (default 8729; 0 chooses a free port)")
    parser.add_argument("--proxy-port", type=int, default=8731, help="App proxy port (default 8731)")
    parser.add_argument("--web-port", type=int, default=8732, help="App web port (default 8732)")
    app_options = parser.add_mutually_exclusive_group()
    app_options.add_argument("--no-app", action="store_true", help="Start without the App preview")
    app_options.add_argument("--app-web", type=Path, metavar="DIR", help="Serve a prebuilt App preview")
    app_options.add_argument("--export-app", type=Path, metavar="DIR", help="Copy the App build and exit")
    parser.add_argument("--shell-port", type=int, help="Demo shell port (default: choose a free port)")
    parser.add_argument("--no-shell", action="store_true", help="Start the live stack without the demo shell")
    parser.add_argument("--tagger", action="store_true", help="Enable Codex text tags in the demo shell")
    parser.add_argument("--realistic", nargs="?", type=int, const=7, metavar="SEED",
                        help="Use seeded fixture judgment and App response delays (default seed: 7)")
    parser.add_argument("--episode", default="ep_9031", choices=sorted(PROFILES))
    parser.add_argument("--keep", action="store_true", help="Resume the previous run on this checkout and port")
    parser.add_argument("--peer-ports", type=int, nargs=3, metavar=("FIXTURE", "MQTT", "HUB"),
                        help="Use these ports for peer services instead of choosing free ports")
    args = parser.parse_args()
    explicit_ports = [args.port, args.proxy_port, args.web_port, *(args.peer_ports or [])]
    if args.shell_port is not None:
        explicit_ports.append(args.shell_port)
    if any(not 0 < port <= 65535 for port in explicit_ports):
        parser.error("ports must be between 1 and 65535")
    if not 0 <= args.start_port <= 65535:
        parser.error("--start-port must be between 0 and 65535")
    if args.no_shell and args.shell_port is not None:
        parser.error("--shell-port requires the demo shell")
    if args.no_shell and args.tagger:
        parser.error("--tagger requires the demo shell")
    if not re.fullmatch(r"h_[a-z0-9]+", args.household):
        parser.error("--household requires a household ID such as h_042")
    if not args.server and args.household != HOUSEHOLD:
        parser.error("the built-in fixture uses h_042; use --server for another household")
    if args.server and args.realistic is not None:
        parser.error("--realistic requires the built-in fixture")
    if args.server and args.export_app is not None:
        parser.error("--export-app requires the built-in fixture")
    if args.app_web is not None:
        args.app_web = args.app_web.resolve()
        if not (args.app_web / "index.html").is_file():
            parser.error("--app-web DIR must contain index.html")

    clock_url = None
    if args.server:
        hub_key = os.getenv("SPIRA_HUB_KEY", "").strip()
        app_token = os.getenv("SPIRA_APP_TOKEN", "").strip()
        if not hub_key or not app_token:
            print(KEY_GUIDE, file=sys.stderr)
            return 1
        try:
            check_server(args.server)
        except RuntimeError as error:
            print(f"demo-up: {error}", file=sys.stderr)
            return 1
        clock_url = server_clock(args.server)
        defines = {
            "SPIRA_BASE_URL": origin(args.proxy_port),
            "SPIRA_HOUSEHOLD_ID": args.household, "SPIRA_PEER": "server",
        }
    else:
        onboarding = ROOT / "contracts/fixtures/ep_9031/household.created.json"
        hub_key = HouseholdCreated.model_validate_json(onboarding.read_text(encoding="utf-8")).hub_api_key
        app_token = APP_TOKEN
        defines = fixture_defines(args.proxy_port, args.household, hub_key)
    if args.export_app is not None:
        try:
            export_app(args.export_app.resolve(), defines)
        except (OSError, RuntimeError) as error:
            print(f"demo-up: {error}", file=sys.stderr)
            return 1
        return 0

    requests = dict(zip(("fixture", "mqtt", "hub"), args.peer_ports or [0, 0, 0], strict=True))
    if args.server:
        del requests["fixture"]
    requests["sim"] = args.port
    requests["start"] = args.start_port
    if not args.no_shell:
        requests["shell"] = args.shell_port or 0
    mosquitto = shutil.which("mosquitto") or next(
        (path for path in ("/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto", "/usr/sbin/mosquitto")
         if Path(path).exists()), None)
    if mosquitto is None:
        sys.exit("mosquitto not found: macOS `brew install mosquitto`, Linux/WSL2 `sudo apt install mosquitto`")
    directory = run_directory(args.port, args.episode, args.server, args.household)
    with (directory / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("this checkout already has a demo running on the requested port")
        return run(args, mosquitto, directory, requests, hub_key, app_token, defines, clock_url)


def run(args, mosquitto, directory, requests, hub_key, app_token, defines, clock_url):
    latest = directory / "latest"
    if args.keep and latest.exists():
        logs = directory / latest.read_text(encoding="utf-8").strip()
    else:
        logs = Path(tempfile.mkdtemp(prefix="run-", dir=directory))
    sim_host = "0.0.0.0" if args.sim_lan_ip else "127.0.0.1"
    operator_token = secrets.token_urlsafe(18)
    reset_token = None if args.no_shell else secrets.token_urlsafe(24)
    processes = []
    peer_names = {"fixture", "mosquitto", "hub", "simulator"}
    start_page = ExitStack()
    stopping = False
    reset_requests = Queue()
    resetting = Lock()

    def wait(what, probe, seconds=20):
        end = time.monotonic() + seconds
        while not stopping and time.monotonic() < end:
            try:
                if probe():
                    return
            except OSError:
                pass
            time.sleep(0.25)
        if stopping:
            raise KeyboardInterrupt
        raise RuntimeError(f"{what} did not become ready")

    def launch(name, cmd, cwd, **env):
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith(("SPIRA_", "WORLD_", "MQTT_", "DEMO_"))}
        with (logs / f"{name}.log").open("a") as log:
            proc = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env={
                **clean, "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": os.pathsep.join([str(CONTRACTS), str(ROOT)]), **env})
        processes.append((name, proc))
        return proc

    def stop(names=None):
        selected = [(name, proc) for name, proc in processes if names is None or name in names]
        for _, proc in reversed(selected):
            if proc.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGTERM)
        for entry in selected:
            _, proc = entry
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            processes.remove(entry)

    def request_reset():
        if not resetting.acquire(blocking=False):
            return 409
        try:
            result = Future()
            reset_requests.put(result)
            return result.result()
        finally:
            resetting.release()

    def build(command, cwd):
        if args.server:
            command = [*command, "--no-web-resources-cdn"]
            if os.getenv("UV_OFFLINE") == "1":
                if status := build_process([command[0], "pub", "get", "--offline"], cwd):
                    return status
                command.append("--no-pub")
        return build_process(command, cwd)

    def build_process(command, cwd):
        proc = launch("app-build", command, cwd, TMPDIR=str(state_root()))
        while not stopping:
            if (status := proc.poll()) is not None:
                processes.remove(("app-build", proc))
                return status
            time.sleep(0.2)
        stop()
        raise KeyboardInterrupt

    def request_stop(*_):
        # The launcher and uv can both forward the same signal to this process.
        nonlocal stopping
        stopping = True

    def start_peers(keep):
        initial_clock = None
        if not keep:
            state_files = ["hub.db", "world.db"]
            if not args.server:
                state_files.extend(["fixture.state", "fixture.tmp"])
            for name in state_files:
                (logs / name).unlink(missing_ok=True)
                if name.endswith(".db"):
                    for suffix in ("-wal", "-shm", "-journal"):
                        (logs / f"{name}{suffix}").unlink(missing_ok=True)
        if not args.server:
            state = logs / "fixture.state"
            resume = keep and state.exists()
            fixture_cmd = [sys.executable, str(Path(__file__).with_name("demo_fixture.py")),
                           "--episode", args.episode, "--port", str(ports["fixture"]),
                           "--state", str(state)]
            if not args.no_shell:
                fixture_cmd.append("--scene-controls")
            if args.realistic is not None:
                fixture_cmd.extend(["--realistic", str(args.realistic)])
            launch("fixture", fixture_cmd, ROOT)
            wait("fixture Server", lambda: read_json(f"{server}/health"))
            if not resume:
                episode_path = ROOT / "contracts/fixtures" / args.episode / "episode.json"
                episode = Episode.model_validate_json(episode_path.read_bytes())
                initial_clock = datetime.fromisoformat(episode.shared_at) - timedelta(seconds=60)
                request = urllib.request.Request(
                    clock_url, data=json.dumps({"set_to": initial_clock.isoformat()}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                read_json(request)
        launch("mosquitto", [mosquitto, "-p", str(ports["mqtt"])], logs)
        wait("MQTT broker", lambda: socket.create_connection(("127.0.0.1", ports["mqtt"]), timeout=1).close() or True)

        prefix = f"spira/demo/{args.household}"
        installation = logs / "installation.json"
        write_demo_installation(installation, args.household)
        profile = ROOT / "simulator/spira_simulator/profiles" / PROFILES[args.episode]
        profile_data = json.loads(profile.read_text(encoding="utf-8"))
        if args.server:
            profile_data.update(household_id=args.household, display_name="우리 집")
            profile = logs / "profile.json"
            profile.write_text(json.dumps(profile_data, ensure_ascii=False), encoding="utf-8")
        home_name = profile_data.get("display_name") or "우리 집"
        clock_env = {"SPIRA_DEMO_CLOCK_URL": clock_url} if clock_url else {}
        launch("hub", [sys.executable, "-m", "hub.spira_hub", "--port", str(ports["hub"]),
                       "--db", str(logs / "hub.db"), "--installation", str(installation), "--home-name", home_name],
               ROOT, SPIRA_SERVER_URL=server, SPIRA_HOUSEHOLD=args.household, SPIRA_HUB_KEY=hub_key,
               **clock_env,
               SPIRA_MQTT_PORT=str(ports["mqtt"]), SPIRA_MQTT_PREFIX=prefix)

        launch("simulator", [sys.executable, str(Path(__file__).with_name("demo_simulator.py")),
                             "--host", sim_host, "--port", str(ports["sim"])], ROOT / "simulator",
               MQTT_HOST="127.0.0.1", MQTT_PORT=str(ports["mqtt"]), MQTT_PREFIX=prefix,
               WORLD_DB=str(logs / "world.db"),
               WORLD_PROFILE=str(profile),
               WORLD_OPERATOR="1", WORLD_OPERATOR_TOKEN=operator_token,
               WORLD_PLANS=f"{server}/v1/hub/plans?household={args.household}", WORLD_PLANS_TOKEN=hub_key,
               WORLD_HUB_STATE_URL=f"{urls['hub']}/state",
               # The shell's house sends person actions to the Simulator.
               **({"WORLD_HOUSE_SHELL_ORIGIN": urls["shell"]} if "shell" in urls else {}))
        wait("Simulator", lambda: read_json(urls["sim"] + "/health")["mqtt"]["connected"])
        wait("Hub", lambda: read_json(urls["hub"] + "/health")["device_online"], seconds=30)
        if initial_clock is not None:
            def world_clock_ready():
                now = datetime.fromisoformat(read_json(urls["sim"] + "/sim/snapshot")["now"])
                return initial_clock <= now < initial_clock + timedelta(minutes=5)

            wait("Simulator fixture clock", world_clock_ready)

    def reset_peers(result):
        status = 503
        try:
            stop(peer_names)
            start_peers(keep=False)
            status = 204
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            stop(peer_names)
            print(f"demo-up reset: {error}\nLogs: {logs}", file=sys.stderr, flush=True)
        finally:
            result.set_result(status)

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        web = args.app_web
        app_message = None
        if web is None and not args.no_app:
            web, hit = cached_app(defines, build)
            if web is None:
                if args.server:
                    raise RuntimeError("앱 미리보기에 Flutter가 필요해요. 앱을 생략하려면 --no-app을 쓰세요.")
                app_message = FLUTTER_REQUIRED
            else:
                app_message = "App build: cache hit" if hit else "App build: built"
        if web:
            requests.update(proxy=args.proxy_port, app=args.web_port)
        try:
            ports = choose_ports(requests, sim_host)
        except OSError as error:
            raise RuntimeError(f"could not reserve its ports: {error}") from error
        urls = {name: origin(port) for name, port in ports.items() if name != "mqtt"}
        server = args.server or urls["fixture"]
        if not args.server:
            clock_url = f"{server}/v1/demo/clock"
        start_peers(args.keep)
        if web:
            if args.server:
                launch("app-proxy", [sys.executable, "-m", "uvicorn", "scripts.demo_app_proxy:create_app", "--factory",
                                     "--host", "127.0.0.1", "--port", str(ports["proxy"]), "--no-access-log"],
                       ROOT, SPIRA_SERVER_URL=server, SPIRA_HOUSEHOLD=args.household,
                       SPIRA_APP_TOKEN=app_token, SPIRA_WEB_ORIGIN=urls["app"])
            else:
                launch("app-proxy", proxy_command(server, urls["hub"], ports["proxy"], ports["app"]), ROOT)
            proxy_health = urllib.request.Request(urls["proxy"] + "/health", headers={"Origin": urls["app"]})
            wait("App proxy", lambda: reachable(proxy_health))
            launch("app-web", web_command(web, ports["app"]), ROOT)
            wait("App preview", lambda: reachable(urls["app"] + "/"))

        if not args.no_shell:
            shell_env = ({"DEMO_RECORDINGS_DIR": str(logs / "recordings")} if args.server
                         else {"DEMO_FIXTURE_EPISODE": args.episode,
                               "DEMO_NUMBERS_PATH": str(ROOT / "server/config/numbers.yaml")})
            launch("shell", [sys.executable, "-m", "uvicorn", "demo:app", "--host", "127.0.0.1",
                             "--port", str(ports["shell"]), "--no-access-log", "--no-proxy-headers"], ROOT / "demo-shell",
                   DEMO_SIMULATOR_URL=urls["sim"], DEMO_OPERATOR_TOKEN=operator_token,
                   DEMO_SERVER_URL=server, DEMO_APP_TOKEN=app_token, DEMO_HOUSEHOLD=args.household,
                   DEMO_RESET_URL=urls["start"] + "/reset", DEMO_RESET_TOKEN=reset_token,
                   DEMO_HUB_URL=urls["hub"], DEMO_APP_URL=urls.get("app", ""), **shell_env,
                   DEMO_TAGGER="off" if args.server else os.getenv("DEMO_TAGGER", "codex" if args.tagger else "off"))
            wait("Demo shell", lambda: reachable(urls["shell"] + "/demo"))

        viewer_url = urls["sim"] + "/sim/viewer"
        hub_url = urls["hub"] + "/"
        operator_url = f"http://{args.sim_lan_ip or '127.0.0.1'}:{ports['sim']}/operator"
        links = {"viewer": viewer_url, "operator": operator_url, "hub": hub_url}
        if args.server:
            links["server"] = server
        if web:
            links["app"] = urls["app"] + "/"
        if not args.no_shell:
            links["shell"] = urls["shell"] + "/demo"
        window = None
        start_port = start_page.enter_context(serve_start_page(
            ports["start"], links, lambda: window,
            lambda: (datetime.fromisoformat(read_json(clock_url)["now"]) if clock_url
                     else datetime.now(ZoneInfo("Asia/Seoul"))),
            reset=request_reset, reset_token=reset_token,
        ))
        selected = latest.with_suffix(".tmp")
        selected.write_text(logs.name, encoding="utf-8")
        selected.replace(latest)

        service_urls = (
            f"Viewer:    {viewer_url}\n"
            f"Hub:       {hub_url}\n"
        )
        if args.server:
            service_urls += f"Server:    {server}\n"
        else:
            service_urls += f"Fixture:   {server}/health  (예시 판단, 추론 아님)\nControl:   {server}/_fixture/control\n"
        if clock_url:
            service_urls += f"Clock:     {clock_url}\n"
        url_file = logs / "urls.txt"
        url_file.write_text(service_urls, encoding="utf-8")
        print(f"시작 페이지: http://127.0.0.1:{start_port}/", flush=True)
        if web:
            print(f"App:       {links['app']}")
        if "shell" in links:
            print(f"Demo:      {links['shell']}")
        print(service_urls, end="")
        credentials = f"  (operator / {operator_token})" if args.sim_lan_ip else ""
        print(f"집에서 일어나는 일: {operator_url}{credentials}")
        if not args.server:
            print(f"Home key (우리 집): {hub_key}")
        if app_message:
            print(app_message)
        if not web and not args.server:
            print(f"App preview: app/scripts/browser-demo --demo-port {ports['sim']} "
                  f"--proxy-port {args.proxy_port} --web-port {args.web_port} --stack-log {url_file}")
        print(f"Logs:      {logs}\nCtrl-C to stop.", flush=True)
        while not stopping:
            try:
                result = reset_requests.get(timeout=1)
            except Empty:
                result = None
            if result is not None:
                window = None
                reset_peers(result)
            for name, proc in processes:
                if proc.poll() is not None:
                    raise RuntimeError(f"{name} exited ({proc.returncode}); see {logs / (name + '.log')}")
            with suppress(OSError, ValueError, KeyError):
                current = guest_window(read_json(urls["hub"] + "/state"))
                previous, window = window, current
                if current and current != previous:
                    seoul = ZoneInfo("Asia/Seoul")
                    times = "–".join(bound.astimezone(seoul).strftime("%H:%M") for bound in window)
                    print(f"손님 맞이: {times}", flush=True)
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError) as error:
        print(f"demo-up: {error}\nLogs: {logs}", file=sys.stderr)
        return 1
    finally:
        start_page.close()
        stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
