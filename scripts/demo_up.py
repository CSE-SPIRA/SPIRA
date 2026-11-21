"""Start the fixture Server, MQTT broker, Simulator, Hub, and App preview.

Run through scripts/demo-up for the Python environment. Ctrl-C stops everything.
"""

import argparse
import fcntl
import hashlib
import json
import os
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
from contextlib import ExitStack, suppress
from ipaddress import IPv4Address
from pathlib import Path
from zoneinfo import ZoneInfo

from spira_contracts.household_created import HouseholdCreated

from app.scripts.browser_demo_web import (
    APP_TOKEN, FLUTTER_REQUIRED, cached_web, fixture_defines, proxy_command, temporary_root,
    web_command,
)
from demo_start import guest_window, serve_start_page

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts/generated/python"
HOUSEHOLD = "h_042"
PROFILES = {"ep_9031": "ep_9031.json"}


def write_demo_installation(path):
    base = ROOT / "hub/installation.example.json"
    additions = Path(__file__).with_name("demo-devices.json")
    installation = json.loads(base.read_text(encoding="utf-8"))
    demo = json.loads(additions.read_text(encoding="utf-8"))
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


def run_directory(port, episode):
    temp = temporary_root()
    identity = hashlib.sha256(f"{ROOT}:{port}:{episode}".encode()).hexdigest()[:16]
    path = temp / f"spira-demo-{os.getuid()}-{identity}"
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        sys.exit(f"demo-up state directory must be private and owned by the current user: {path}")
    return path


def export_app(destination, defines):
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise RuntimeError("--export-app requires a new or empty directory")
    web, hit = cached_web(defines, lambda command, cwd: subprocess.call(command, cwd=cwd))
    if web is None:
        raise RuntimeError(FLUTTER_REQUIRED)
    shutil.copytree(web, destination, dirs_exist_ok=True)
    source = "cache hit" if hit else "built"
    print(f"App build: {source}\nApp export: {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--episode", default="ep_9031", choices=sorted(PROFILES))
    parser.add_argument("--starts-in", type=int, default=90,
                        help="Seconds from upload to the event start in the fixture replay")
    parser.add_argument("--guest-window", type=int, default=600,
                        help="Seconds from the replay event start to accept guest arrivals (default 600)")
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
    if not 1 <= args.starts_in <= 3600:
        parser.error("--starts-in must be between 1 and 3600 seconds")
    if not 1 <= args.guest_window <= 3600:
        parser.error("--guest-window must be between 1 and 3600 seconds")
    if args.no_shell and args.shell_port is not None:
        parser.error("--shell-port requires the demo shell")
    if args.app_web is not None:
        args.app_web = args.app_web.resolve()
        if not (args.app_web / "index.html").is_file():
            parser.error("--app-web DIR must contain index.html")

    onboarding = ROOT / "contracts/fixtures/ep_9031/household.created.json"
    hub_key = HouseholdCreated.model_validate_json(onboarding.read_text(encoding="utf-8")).hub_api_key
    defines = fixture_defines(args.proxy_port, HOUSEHOLD, hub_key)
    if args.export_app is not None:
        try:
            export_app(args.export_app.resolve(), defines)
        except (OSError, RuntimeError) as error:
            print(f"demo-up: {error}", file=sys.stderr)
            return 1
        return 0

    requests = dict(zip(("fixture", "mqtt", "hub"), args.peer_ports or [0, 0, 0], strict=True))
    requests["sim"] = args.port
    requests["start"] = args.start_port
    if not args.no_shell:
        requests["shell"] = args.shell_port or 0
    mosquitto = shutil.which("mosquitto") or next(
        (path for path in ("/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto", "/usr/sbin/mosquitto")
         if Path(path).exists()), None)
    if mosquitto is None:
        sys.exit("mosquitto not found: macOS `brew install mosquitto`, Linux/WSL2 `sudo apt install mosquitto`")
    directory = run_directory(args.port, args.episode)
    with (directory / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("this checkout already has a demo running on the requested port")
        return run(args, mosquitto, directory, requests, hub_key, defines)


def run(args, mosquitto, directory, requests, hub_key, defines):
    latest = directory / "latest"
    if args.keep and latest.exists():
        logs = directory / latest.read_text(encoding="utf-8").strip()
    else:
        logs = Path(tempfile.mkdtemp(prefix="run-", dir=directory))
    sim_host = "0.0.0.0" if args.sim_lan_ip else "127.0.0.1"
    operator_token = secrets.token_urlsafe(18)
    processes = []
    start_page = ExitStack()
    stopping = False

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

    def stop():
        for _, proc in reversed(processes):
            if proc.poll() is None:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGTERM)
        for _, proc in processes:
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        processes.clear()

    def build(command, cwd):
        proc = launch("app-build", command, cwd, TMPDIR=str(temporary_root()))
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

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        web = args.app_web
        app_message = None
        if web is None and not args.no_app:
            web, hit = cached_web(defines, build)
            if web is None:
                app_message = FLUTTER_REQUIRED
            else:
                app_message = "App build: cache hit" if hit else "App build: built"
        if web:
            requests.update(proxy=args.proxy_port, app=args.web_port)
        try:
            ports = choose_ports(requests, sim_host)
        except OSError as error:
            raise RuntimeError(f"could not reserve its ports: {error}") from error
        urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items() if name != "mqtt"}

        fixture_cmd = [sys.executable, str(Path(__file__).with_name("demo_fixture.py")),
                       "--episode", args.episode, "--port", str(ports["fixture"]),
                       "--state", str(logs / "fixture.state"), "--starts-in", str(args.starts_in),
                       "--guest-window", str(args.guest_window)]
        if not args.no_shell:
            fixture_cmd.append("--scene-controls")
        launch("fixture", fixture_cmd, ROOT)
        wait("fixture Server", lambda: read_json(urls["fixture"] + "/health"))
        launch("mosquitto", [mosquitto, "-p", str(ports["mqtt"])], logs)
        wait("MQTT broker", lambda: socket.create_connection(("127.0.0.1", ports["mqtt"]), timeout=1).close() or True)

        prefix = f"spira/demo/{HOUSEHOLD}"
        installation = logs / "installation.json"
        write_demo_installation(installation)
        profile = ROOT / "simulator/spira_simulator/profiles" / PROFILES[args.episode]
        home_name = json.loads(profile.read_text(encoding="utf-8")).get("display_name") or "우리 집"
        launch("hub", [sys.executable, "-m", "hub.spira_hub", "--port", str(ports["hub"]),
                       "--db", str(logs / "hub.db"), "--installation", str(installation), "--home-name", home_name],
               ROOT, SPIRA_SERVER_URL=urls["fixture"], SPIRA_HOUSEHOLD=HOUSEHOLD, SPIRA_HUB_KEY=hub_key,
               SPIRA_MQTT_PORT=str(ports["mqtt"]), SPIRA_MQTT_PREFIX=prefix)

        launch("simulator", [sys.executable, str(Path(__file__).with_name("demo_simulator.py")),
                             "--host", sim_host, "--port", str(ports["sim"])], ROOT / "simulator",
               MQTT_HOST="127.0.0.1", MQTT_PORT=str(ports["mqtt"]), MQTT_PREFIX=prefix,
               WORLD_DB=str(logs / "world.db"),
               WORLD_PROFILE=str(profile),
               WORLD_OPERATOR="1", WORLD_OPERATOR_TOKEN=operator_token,
               WORLD_PLANS=f"{urls['fixture']}/v1/hub/plans?household={HOUSEHOLD}", WORLD_PLANS_TOKEN=hub_key,
               WORLD_HUB_STATE_URL=f"{urls['hub']}/state")
        wait("Simulator", lambda: read_json(urls["sim"] + "/health")["mqtt"]["connected"])
        wait("Hub", lambda: read_json(urls["hub"] + "/health")["device_online"], seconds=30)
        if not args.no_shell:
            launch("shell", [sys.executable, "-m", "uvicorn", "demo:app", "--host", "127.0.0.1",
                             "--port", str(ports["shell"]), "--no-access-log"], ROOT / "demo-shell",
                   DEMO_SIMULATOR_URL=urls["sim"], DEMO_OPERATOR_TOKEN=operator_token,
                   DEMO_SERVER_URL=urls["fixture"], DEMO_APP_TOKEN=APP_TOKEN, DEMO_HOUSEHOLD=HOUSEHOLD,
                   DEMO_HUB_URL=urls["hub"], DEMO_FIXTURE_EPISODE=args.episode, DEMO_STARTS_IN=str(args.starts_in),
                   DEMO_NUMBERS_PATH=str(ROOT / "server/config/numbers.yaml"))
            wait("Demo shell", lambda: reachable(urls["shell"] + "/demo"))
        if web:
            launch("app-proxy", proxy_command(urls["fixture"], urls["hub"], ports["proxy"], ports["app"]), ROOT)
            proxy_health = urllib.request.Request(urls["proxy"] + "/health", headers={"Origin": urls["app"]})
            wait("App proxy", lambda: reachable(proxy_health))
            launch("app-web", web_command(web, ports["app"]), ROOT)
            wait("App preview", lambda: reachable(urls["app"] + "/"))

        viewer_url = urls["sim"] + "/sim/viewer"
        hub_url = urls["hub"] + "/"
        operator_url = f"http://{args.sim_lan_ip or '127.0.0.1'}:{ports['sim']}/operator"
        links = {"viewer": viewer_url, "operator": operator_url, "hub": hub_url}
        if web:
            links["app"] = urls["app"] + "/"
        if not args.no_shell:
            links["shell"] = urls["shell"] + "/demo"
        window = None
        start_port = start_page.enter_context(serve_start_page(ports["start"], links, lambda: window))
        selected = latest.with_suffix(".tmp")
        selected.write_text(logs.name, encoding="utf-8")
        selected.replace(latest)

        service_urls = (
            f"Viewer:    {viewer_url}\n"
            f"Hub:       {hub_url}\n"
            f"Fixture:   {urls['fixture']}/health  (예시 판단, 추론 아님)\n"
        )
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
        print(f"Home key (우리 집): {hub_key}")
        if app_message:
            print(app_message)
        if not web:
            print(f"App preview: app/scripts/browser-demo --demo-port {ports['sim']} "
                  f"--proxy-port {args.proxy_port} --web-port {args.web_port} --stack-log {url_file}")
        print(f"Logs:      {logs}\nCtrl-C to stop.")
        # The window opens guest_window_before_min (demo: 1 minute, server/config/numbers.yaml)
        # before the party and closes --guest-window seconds after it starts.
        opens = max(args.starts_in - 60, 0)
        minutes, seconds = divmod(args.starts_in + args.guest_window - opens, 60)
        duration = " ".join(part for part in (f"{minutes}분" if minutes else "",
                                              f"{seconds}초" if seconds else "") if part)
        print(f"손님 맞이: 공유 후 약 {opens}초부터 {duration}", flush=True)
        while not stopping:
            for name, proc in processes:
                if proc.poll() is not None:
                    raise RuntimeError(f"{name} exited ({proc.returncode}); see {logs / (name + '.log')}")
            with suppress(OSError, ValueError, KeyError):
                current = guest_window(read_json(urls["hub"] + "/state"))
                if current and current != window:
                    window = current
                    seoul = ZoneInfo("Asia/Seoul")
                    times = "–".join(bound.astimezone(seoul).strftime("%H:%M") for bound in window)
                    print(f"손님 맞이: {times}", flush=True)
            time.sleep(1)
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
