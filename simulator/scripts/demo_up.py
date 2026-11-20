"""Start the demo stack from this checkout: fixture Server, MQTT broker, Simulator, Hub.

Run through simulator/scripts/demo-up (it provides the Python environment).
Open the printed /demo address. Ctrl-C stops everything.
"""

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/generated/python"
APP_TOKEN = "demo"
HOUSEHOLD = "h_042"
PROFILES = {"ep_9031": "ep_9031.json"}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(url, *, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=5) as res:
        text = res.read()
        return json.loads(text) if text else None


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8730, help="Simulator and demo page port (default 8730)")
    parser.add_argument("--episode", default="ep_9031", choices=sorted(PROFILES))
    parser.add_argument("--starts-in", type=int, default=90,
                        help="Seconds from upload to the event start in the fixture replay")
    args = parser.parse_args()

    mosquitto = shutil.which("mosquitto") or "/opt/homebrew/sbin/mosquitto"
    if not Path(mosquitto).exists():
        sys.exit("mosquitto not found (brew install mosquitto)")
    logs = Path(tempfile.mkdtemp(prefix="spira-demo-", dir="/private/tmp" if Path("/private/tmp").exists() else None))
    ports = {"fixture": free_port(), "mqtt": free_port(), "hub": free_port(), "sim": args.port}
    urls = {name: f"http://127.0.0.1:{port}" for name, port in ports.items() if name != "mqtt"}
    operator_token = secrets.token_urlsafe(18)
    processes = []

    def launch(name, cmd, cwd, **env):
        log = (logs / f"{name}.log").open("w")
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith(("SPIRA_", "WORLD_", "MQTT_", "DEMO_"))}
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env={
            **clean, "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join([str(CONTRACTS), str(ROOT), str(ROOT / "simulator")]), **env})
        processes.append((name, proc))
        return proc

    def stop(*_):
        for _, proc in reversed(processes):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for _, proc in processes:
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)

    signal.signal(signal.SIGTERM, lambda *_: (stop(), sys.exit(0)))
    try:
        launch("fixture", [sys.executable, "-m", "hub.tests.fixture_server", "--scene-controls",
                           "--episode", args.episode, "--port", str(ports["fixture"])], ROOT, DEMO_MODE="1")
        wait("fixture Server", lambda: call(urls["fixture"] + "/health"))
        app = {"Authorization": f"Bearer {APP_TOKEN}"}
        created = call(urls["fixture"] + "/v1/households", method="POST", body={"household_types": []}, headers=app)
        hub_key = created["hub_api_key"]

        launch("mosquitto", [mosquitto, "-p", str(ports["mqtt"])], logs)
        wait("MQTT broker", lambda: socket.create_connection(("127.0.0.1", ports["mqtt"]), timeout=1).close() or True)

        prefix = f"spira/demo/{HOUSEHOLD}"
        launch("hub", [sys.executable, "-m", "hub.spira_hub", "--port", str(ports["hub"]),
                       "--db", str(logs / "hub.db"), "--installation", str(ROOT / "hub/installation.example.json")],
               ROOT, SPIRA_SERVER_URL=urls["fixture"], SPIRA_HOUSEHOLD=HOUSEHOLD, SPIRA_HUB_KEY=hub_key,
               SPIRA_MQTT_PORT=str(ports["mqtt"]), SPIRA_MQTT_PREFIX=prefix)

        launch("simulator", [sys.executable, "-m", "uvicorn", "spira_simulator.api:app", "--host", "127.0.0.1",
                             "--port", str(ports["sim"]), "--no-access-log"], ROOT / "simulator",
               MQTT_HOST="127.0.0.1", MQTT_PORT=str(ports["mqtt"]), MQTT_PREFIX=prefix,
               WORLD_DB=str(logs / "world.db"),
               WORLD_PROFILE=str(ROOT / "simulator/spira_simulator/profiles" / PROFILES[args.episode]),
               WORLD_OPERATOR="1", WORLD_OPERATOR_TOKEN=operator_token,
               WORLD_PLANS=f"{urls['fixture']}/v1/hub/plans?household={HOUSEHOLD}", WORLD_PLANS_TOKEN=hub_key,
               WORLD_HUB_STATE_URL=f"{urls['hub']}/state",
               WORLD_DEMO="1", DEMO_SERVER_URL=urls["fixture"], DEMO_APP_TOKEN=APP_TOKEN,
               DEMO_HUB_URL=urls["hub"], DEMO_FIXTURE_EPISODE=args.episode, DEMO_STARTS_IN=str(args.starts_in))
        wait("Simulator", lambda: call(urls["sim"] + "/health")["mqtt"]["connected"])
        wait("Hub", lambda: call(urls["hub"] + "/health")["device_online"], seconds=30)

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
