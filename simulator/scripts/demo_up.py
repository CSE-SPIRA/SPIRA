"""Start the demo stack from this checkout: fixture Server, MQTT broker, Simulator, Hub.

Run through simulator/scripts/demo-up (it provides the Python environment).
Open the printed /demo address. Ctrl-C stops everything.
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
from contextlib import ExitStack
from pathlib import Path

from spira_contracts.household_created import HouseholdCreated

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/generated/python"
APP_TOKEN = "demo"
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


def choose_ports(port, peers):
    with ExitStack() as stack:
        numbers = []
        for requested in [port, *(peers or [0, 0, 0])]:
            listener = stack.enter_context(socket.socket())
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", requested))
            listener.listen()
            numbers.append(listener.getsockname()[1])
    return dict(zip(("sim", "fixture", "mqtt", "hub"), numbers, strict=True))


def read_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def wait(what, probe, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        try:
            if probe():
                return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{what} did not become ready")


def run_directory(port, episode):
    temp = Path("/private/tmp") if Path("/private/tmp").exists() else Path(tempfile.gettempdir())
    identity = hashlib.sha256(f"{ROOT}:{port}:{episode}".encode()).hexdigest()[:16]
    path = temp / f"spira-demo-{os.getuid()}-{identity}"
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        sys.exit(f"demo-up state directory must be private and owned by the current user: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8730, help="Simulator and demo page port (default 8730)")
    parser.add_argument("--episode", default="ep_9031", choices=sorted(PROFILES))
    parser.add_argument("--starts-in", type=int, default=90,
                        help="Seconds from upload to the event start in the fixture replay")
    parser.add_argument("--keep", action="store_true", help="Resume the previous run on this checkout and port")
    parser.add_argument("--peer-ports", type=int, nargs=3, metavar=("FIXTURE", "MQTT", "HUB"),
                        help="Use these ports for peer services instead of choosing free ports")
    args = parser.parse_args()
    if any(not 0 < port <= 65535 for port in [args.port, *(args.peer_ports or [])]):
        parser.error("ports must be between 1 and 65535")
    mosquitto = shutil.which("mosquitto") or "/opt/homebrew/sbin/mosquitto"
    if not Path(mosquitto).exists():
        sys.exit("mosquitto not found (brew install mosquitto)")
    directory = run_directory(args.port, args.episode)
    with (directory / "lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("this checkout already has a demo running on the requested port")
        return run(args, mosquitto, directory)


def run(args, mosquitto, directory):
    latest = directory / "latest"
    if args.keep and latest.exists():
        logs = directory / latest.read_text(encoding="utf-8").strip()
    else:
        logs = Path(tempfile.mkdtemp(prefix="run-", dir=directory))
    try:
        ports = choose_ports(args.port, args.peer_ports)
    except OSError as error:
        sys.exit(f"demo-up could not reserve its ports: {error}")
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items() if name != "mqtt"}
    operator_token = secrets.token_urlsafe(18)
    processes = []

    def launch(name, cmd, cwd, **env):
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith(("SPIRA_", "WORLD_", "MQTT_", "DEMO_"))}
        with (logs / f"{name}.log").open("a") as log:
            proc = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env={
                **clean, "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": os.pathsep.join([str(CONTRACTS), str(ROOT), str(ROOT / "simulator")]), **env})
        processes.append((name, proc))
        return proc

    def stop():
        for _, proc in reversed(processes):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for _, proc in processes:
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        launch("fixture", [sys.executable, str(Path(__file__).with_name("demo_fixture.py")),
                           "--episode", args.episode, "--port", str(ports["fixture"]),
                           "--state", str(logs / "fixture.state")], ROOT)
        wait("fixture Server", lambda: read_json(urls["fixture"] + "/health"))
        onboarding = ROOT / "contracts/fixtures/ep_9031/household.created.json"
        hub_key = HouseholdCreated.model_validate_json(onboarding.read_text(encoding="utf-8")).hub_api_key

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

        launch("simulator", [sys.executable, "-m", "uvicorn", "spira_simulator.api:app", "--host", "127.0.0.1",
                             "--port", str(ports["sim"]), "--no-access-log"], ROOT / "simulator",
               MQTT_HOST="127.0.0.1", MQTT_PORT=str(ports["mqtt"]), MQTT_PREFIX=prefix,
               WORLD_DB=str(logs / "world.db"),
               WORLD_PROFILE=str(profile),
               WORLD_OPERATOR="1", WORLD_OPERATOR_TOKEN=operator_token,
               WORLD_PLANS=f"{urls['fixture']}/v1/hub/plans?household={HOUSEHOLD}", WORLD_PLANS_TOKEN=hub_key,
               WORLD_HUB_STATE_URL=f"{urls['hub']}/state",
               WORLD_DEMO="1", DEMO_SERVER_URL=urls["fixture"], DEMO_APP_TOKEN=APP_TOKEN,
               DEMO_HUB_URL=urls["hub"], DEMO_FIXTURE_EPISODE=args.episode, DEMO_STARTS_IN=str(args.starts_in),
               DEMO_NUMBERS_PATH=str(ROOT / "server/config/numbers.yaml"))
        wait("Simulator", lambda: read_json(urls["sim"] + "/health")["mqtt"]["connected"])
        wait("Hub", lambda: read_json(urls["hub"] + "/health")["device_online"], seconds=30)
        selected = latest.with_suffix(".tmp")
        selected.write_text(logs.name, encoding="utf-8")
        selected.replace(latest)

        print(f"Demo:      {urls['sim']}/demo\n"
              f"Operator:  {urls['sim']}/operator  (operator / {operator_token})\n"
              f"Hub:       {urls['hub']}/\n"
              f"Fixture:   {urls['fixture']}/health  (예시 판단, 추론 아님)\n"
              f"Logs:      {logs}\nCtrl-C to stop.", flush=True)
        while True:
            for name, proc in processes:
                if proc.poll() is not None:
                    raise RuntimeError(f"{name} exited ({proc.returncode}); see {logs / (name + '.log')}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    except RuntimeError as error:
        print(f"demo-up: {error}\nLogs: {logs}", file=sys.stderr)
        return 1
    finally:
        stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
