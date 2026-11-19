"""Wire peers for acceptance tests. The MQTT fake deliberately omits actor truth."""

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx2 as httpx
from spira_contracts.validate import validate

from hub.spira_hub.contracts import Server
from hub.spira_hub.dashboard import create_app
from hub.spira_hub.device import MQTTDevice, SCHEMA
from hub.spira_hub.runtime import Runtime
from hub.spira_hub.store import Store
from hub.tests.fixture_server import create_app as fixture_app

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def fixture(name, episode="ep_9031"):
    return json.loads((FIXTURES / episode / name).read_text())


class Clock:
    def __init__(self, at="2026-10-17T13:40:00+09:00"):
        self.now = datetime.fromisoformat(at)

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)
        return self.now.isoformat()


class Stub:
    """Small fault-injection peer for plans the fixture replay cannot express."""

    def __init__(self, clock, *tasks):
        self.clock = clock
        self.plans = [plan(clock, *tasks)]
        self.paused = False
        self.registry = None
        self.acks = []
        self.events = []
        self.executions = []
        self.packets = []
        self.down = False
        self.reject_delivery = False
        self.pulls = 0

    def advance(self, *tasks, cancelled=None):
        last = self.plans[0]
        self.plans[0] = plan(self.clock, *tasks, version=last["plan_version"] + 1,
                             cancelled=cancelled)

    async def respond(self, request):
        path = request.url.path
        if path.endswith("/plans"):
            self.pulls += 1
            if self.down:
                return httpx.Response(503)
            return httpx.Response(200, json=dict(
                household_id="h_042", paused=self.paused, plans=self.plans,
                devices_revision=self.registry["revision"] if self.registry else 0,
            ))
        raw = json.loads(request.content)
        if path.endswith("/devices"):
            validate(raw, "devices.json")
            self.registry = raw
            return httpx.Response(200, json={"revision": raw["revision"]})
        if path.endswith("/ack"):
            validate(raw, "ack.json")
            self.acks.append(raw)
            return httpx.Response(204)
        self.packets.append(request.content)
        if path.endswith("/events"):
            validate(raw, "event_batch.json")
            self.events.extend(raw)
            if self.reject_delivery:
                return httpx.Response(503)
            return httpx.Response(200, json=dict(
                accepted=[event["event_id"] for event in raw], rejected=[], plans_changed=False,
            ))
        assert path.endswith("/executions")
        validate(raw, "execution_result.json")
        self.executions.append(raw)
        return httpx.Response(503) if self.reject_delivery else httpx.Response(
            200, json={"duplicate": False},
        )

    def transport(self):
        return httpx.MockTransport(self.respond)


def plan(clock, *tasks, version=1, cancelled=None):
    return dict(plan_id="ep_test", household_id="h_042", plan_version=version,
                devices_revision=0, sent_at=clock().isoformat(), tasks=list(tasks),
                cancelled=cancelled or [])


def action(device="light_01", cmd="color", value=None):
    body = dict(device=device, cmd=cmd)
    if value is not None:
        body["value"] = value
    elif cmd == "color":
        body["value"] = {"hue": 330, "saturation": 45, "brightness": 70}
    return body


def task(clock, *actions, n=1, trigger=None, restore=True, end=None):
    return dict(
        task_id=f"t_test#{n}", source="situation", way="run", actions=list(actions or [action()]),
        trigger=trigger or {"time": clock().isoformat()},
        end=end or {"on": "event_end", "restore": restore},
    )


@dataclass
class Native:
    spec: dict
    values: dict
    revisions: dict
    available: bool = True
    job_id: str | None = None


class World:
    def __init__(self, clock, mqtt):
        self.clock = clock
        self.mqtt = mqtt
        self.native = {}
        self.commands = []
        self.replies = {}
        self.revision = 0
        self.read_number = 0
        self.before_read = None
        self.before_command = None
        self.on_read = None
        self.drop_ack = False
        self.unchanged = False
        self.publish_push = True

    def add(self, target, kind, values, commands, *, local=False, substrate="virtual"):
        self.native[target] = Native({
            "target": target, "device_type": kind, "room": None, "substrate": substrate,
            "local_operation_reporting": local, **({"assumption": "Virtual panel assumed"} if local else {}),
            "capabilities": {"commands": commands, "properties": list(values)},
        }, deepcopy(values), {prop: f"initial-{target}-{prop}" for prop in values})

    def emit(self, topic, body, *, retain=False):
        message = SimpleNamespace(
            topic=f"{self.mqtt.prefix}/{topic}", payload=json.dumps(body).encode(), qos=1, retain=retain,
        )
        self.mqtt.receive(message)

    def report(self, target, *, event=None, operation=None, local=False, at=None):
        native = self.native[target]
        at = self.clock().isoformat() if at is None else at
        return dict(schema=SCHEMA, kind="state_report", signal_id="sig_" + uuid4().hex,
                    target=target, event_type=event, world_revision=self.revision,
                    values=deepcopy(native.values), revisions=native.revisions.copy(),
                    occurred_at=at if event else None, observed_at=at, available=native.available,
                    substrate=native.spec["substrate"], job_id=native.job_id, operation_id=operation,
                    local_operation=local)

    def change(self, target, values, *, event=None, operation=None, local=False, job=None):
        self.revision += 1
        native = self.native[target]
        native.values.update(deepcopy(values))
        native.revisions.update({prop: f"revision-{self.revision}-{prop}" for prop in values})
        native.job_id = job
        event = event or f"{native.spec['device_type']}.changed"
        if self.publish_push:
            self.emit("events", self.report(target, event=event, operation=operation, local=local))

    def signal(self, kind, target, *, at=None, signal_id=None, **payload):
        body = dict(schema=SCHEMA, kind="event_signal", signal_id=signal_id or "sig_" + uuid4().hex,
                    target=target, event_type=kind, occurred_at=at or self.clock().isoformat(),
                    payload=payload)
        self.emit("events", body)
        return body

    async def publish(self, topic, payload, *, qos, retain):
        assert qos == 1 and retain is False
        body = json.loads(payload)
        request_id = body["request_id"]
        assert body["schema"] == SCHEMA and request_id not in self.replies
        route = topic.removeprefix(self.mqtt.prefix + "/")
        if route == "discover":
            data = {"devices": [dict(device.spec, available=device.available)
                                for device in self.native.values()]}
        elif route == "read":
            self.read_number += 1
            if self.before_read:
                await self.before_read(body)
            data = self.report(body["target"]) if body["target"] in self.native else None
            if self.on_read:
                data = self.on_read(body, data)
        else:
            assert route == "command"
            self.commands.append(body)
            if self.before_command:
                await self.before_command(body)
            data = self.apply(body)
            if self.drop_ack:
                return
        self.replies[request_id] = data
        self.emit(body["reply_to"].removeprefix(self.mqtt.prefix + "/"),
                  dict(schema=SCHEMA, request_id=request_id, data=data))

    def apply(self, body):
        operation = body["operation_id"]
        native = self.native[body["target"]]
        job = None
        if not native.available:
            status = "UNAVAILABLE"
        elif any(native.revisions.get(prop) != value for prop, value in body["expected"].items()):
            status = "CONFLICT"
        elif body["desired"].keys() - native.values.keys():
            status = "UNSUPPORTED"
        else:
            status = "ACCEPTED"
            if not self.unchanged:
                kind = native.spec["device_type"]
                values = body["desired"].copy()
                event = None
                if kind == "cleaner":
                    values["in_use"] = values["clean"] is not None
                    if values["in_use"]:
                        job = "job_" + uuid4().hex
                        event = "cleaner.started"
                    else:
                        event = "cleaner.stopped"
                self.change(body["target"], values, event=event, operation=operation, job=job)
        return dict(status=status, operation_id=operation, job_id=job)


class Scenario:
    def __init__(self, tmp_path, clock, *, stub=None, episode=None, real_mqtt=None, transport=None):
        self.clock = clock
        self.stub = stub
        self.household = "h_051" if episode == "ep_9120" else "h_042"
        self.path = tmp_path / "installation.json"
        self.db_path = tmp_path / "runtime.sqlite3"
        self.mqtt = MQTTDevice(host="127.0.0.1", port=real_mqtt or 1883,
                               prefix="spira/test", hub_id="hub_test", timeout=0.08 if not real_mqtt else 2)
        key = fixture("household.created.json")["hub_api_key"]
        if transport is None:
            transport = stub.transport() if stub else httpx.ASGITransport(app=fixture_app(episode))
        self.http = httpx.AsyncClient(base_url="http://fixture", transport=transport, headers={
            "X-API-Key": key, "Authorization": "Bearer fixture", "Content-Type": "application/json",
        })
        self.server = Server(self.http, self.household)
        self.world = World(clock, self.mqtt)
        if not real_mqtt:
            self.mqtt.client = self.world
            self.mqtt.online = True

    def write(self, devices, bindings, home_signals=None):
        self.path.write_text(json.dumps({
            "devices": {
                "devices": devices, "household_id": self.household, "revision": 0,
                "updated_at": self.clock().isoformat(),
            },
            "bindings": bindings, "home_signals": home_signals if home_signals is not None else [
                rule("guest_arrived", ("doorbell", "doorbell.rang"), ("lock", "door_lock.unlocked")),
                rule("event_end", ("home", "event_end")),
                {**rule("package.brought_in", ("camera", "camera.package_removed")),
                 "count_field": "removed_count"},
            ],
        }))

    def boot(self):
        self.store = Store(self.db_path, self.household)
        self.runtime = Runtime(self.store, self.server, self.mqtt, self.path,
                               clock=self.clock, verify_seconds=0.25, verify_interval=0.005)
        self.dashboard = httpx.AsyncClient(base_url="http://hub", transport=httpx.ASGITransport(
            app=create_app(self.runtime),
        ))

    async def reconcile(self):
        await self.runtime.discover()
        assert await self.runtime.refresh()
        await self.runtime.flush()

    async def cycle(self):
        await self.runtime.step()
        await self.runtime.flush()

    async def state(self):
        return (await self.dashboard.get("/api/state")).json()

    async def receipts(self):
        return (await self.http.get("/_fixture/receipts")).json()

    async def shutdown(self):
        await self.dashboard.aclose()
        self.store.db.close()

    async def close(self):
        await self.shutdown()
        await self.http.aclose()


def rule(event, *sources):
    return {"event": event, "sources": [{"target": target, "event_type": kind} for target, kind in sources]}


def light_config(*, local=True, substrate="virtual", target="light", logical="light_01"):
    device = deepcopy(fixture("devices.json")["devices"][1])
    device.update(id=logical, substrate=substrate)
    binding = {"target": target, "commands": {"color": "color", "color_temp": "color"}}
    return device, binding, (target, "light", {"color": {"kelvin": 3000}}, ["color", "color_temp"])
