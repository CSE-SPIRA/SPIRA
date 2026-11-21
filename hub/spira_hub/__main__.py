"""Run the Hub on wall time with independent Server and MQTT peers."""

import argparse
import asyncio
import fcntl
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2 as httpx
import uvicorn

from .contracts import Server, identity
from .dashboard import create_app
from .device import MQTTDevice
from .runtime import PULL_INTERVAL, Runtime
from .store import Store


async def repeat(interval, action):
    while True:
        await action()
        await asyncio.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", required=True, type=Path)
    parser.add_argument("--db", default=Path("hub.sqlite3"), type=Path)
    parser.add_argument("--port", default=8088, type=int)
    parser.add_argument("--home-name", default="우리 집", help="Household name for the ledger")
    args = parser.parse_args()
    required = ("SPIRA_SERVER_URL", "SPIRA_HOUSEHOLD", "SPIRA_HUB_KEY")
    if missing := [name for name in required if not os.environ.get(name)]:
        parser.error(f"Set {', '.join(missing)}")

    with args.db.with_suffix(args.db.suffix + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another Hub is using this database")
        run(args)


def run(args):
    household = os.environ["SPIRA_HOUSEHOLD"]
    hub_key = os.environ["SPIRA_HUB_KEY"]
    store = Store(args.db, household)
    with store.db:
        hub_id = store.get("hub_id") or identity("hub")
        store.put("hub_id", hub_id)
    device = MQTTDevice(
        host=os.environ.get("SPIRA_MQTT_HOST") or "127.0.0.1",
        port=int(os.environ.get("SPIRA_MQTT_PORT") or "1883"),
        prefix=os.environ.get("SPIRA_MQTT_PREFIX") or "spira/g0",
        hub_id=hub_id,
        username=os.environ.get("SPIRA_MQTT_USERNAME") or None,
        password=os.environ.get("SPIRA_MQTT_PASSWORD") or None,
    )
    http = httpx.AsyncClient(
        base_url=os.environ["SPIRA_SERVER_URL"], timeout=5,
        headers={"X-API-Key": hub_key, "Content-Type": "application/json"},
    )
    runtime = Runtime(store, Server(http, household), device, args.installation)

    @asynccontextmanager
    async def lifespan(_app):
        async with http, asyncio.TaskGroup() as workers:
            tasks = [
                workers.create_task(device.listen()),
                workers.create_task(repeat(2, runtime.discover)),
                workers.create_task(repeat(PULL_INTERVAL, runtime.refresh)),
                workers.create_task(repeat(0.25, runtime.step)),
                workers.create_task(repeat(1, runtime.flush)),
            ]
            try:
                yield
            finally:
                for task in tasks:
                    task.cancel()

    try:
        uvicorn.run(create_app(runtime, lifespan=lifespan, hub_key=hub_key, home_name=args.home_name),
                    host="127.0.0.1", port=args.port, access_log=False)
    finally:
        store.db.close()


if __name__ == "__main__":
    main()
