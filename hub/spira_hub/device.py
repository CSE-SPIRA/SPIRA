"""MQTT transport for simulator/protocol.md (spira.device.v1)."""

import asyncio
import json
from dataclasses import dataclass

import aiomqtt
from spira_contracts.common import Substrate

from .contracts import identity, offset_time
from .store import encode

SCHEMA = "spira.device.v1"
ACK_STATUSES = {"ACCEPTED", "REJECTED", "UNAVAILABLE", "UNSUPPORTED", "CONFLICT", "PROHIBITED", "UNKNOWN"}
TRUTH_FIELDS = {"actor", "ground_truth_actor", "provenance", "by"}


def observable(value):
    if isinstance(value, dict):
        return {key: observable(item) for key, item in value.items() if key not in TRUTH_FIELDS}
    if isinstance(value, list):
        return [observable(item) for item in value]
    return value


def optional_id(value):
    return value is None or (isinstance(value, str) and bool(value))


def watchable(raw):
    return (
        isinstance(raw, dict)
        and raw.get("schema") == SCHEMA
        and isinstance(raw.get("target"), str)
        and isinstance(raw.get("signal_id"), str)
        and optional_id(raw.get("event_type"))
    )


def report(raw):
    if not watchable(raw) or raw.get("kind") != "state_report":
        return None
    try:
        if not (
            type(raw["available"]) is bool
            and type(raw["world_revision"]) is int and raw["world_revision"] >= 0
            and type(raw["local_operation"]) is bool
            and optional_id(raw["operation_id"])
            and optional_id(raw["job_id"])
            and isinstance(raw["values"], dict)
            and isinstance(raw["revisions"], dict)
            and not (raw["local_operation"] and raw["operation_id"])
        ):
            return None
        Substrate(raw["substrate"])
        observed = offset_time(raw["observed_at"])
        occurred = offset_time(raw["occurred_at"]) if raw.get("occurred_at") else None
        if raw.get("event_type") and (occurred is None or occurred > observed):
            return None
        fields = ("signal_id", "target", "event_type", "world_revision", "values", "revisions",
                  "occurred_at", "observed_at", "available", "substrate", "job_id", "operation_id",
                  "local_operation")
        return {field: observable(raw.get(field)) for field in fields}
    except (KeyError, ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Capability:
    device_type: str
    substrate: str
    commands: frozenset[str]
    properties: frozenset[str]
    local_operation: bool
    assumption: str | None


class MQTTDevice:
    def __init__(self, *, host, port, prefix, hub_id, timeout=3, username=None, password=None):
        self.options = dict(hostname=host, port=port, username=username, password=password)
        self.prefix = prefix.strip("/")
        self.hub_id = hub_id
        self.timeout = timeout
        self.client = None
        self.pending = {}
        self.online = None
        self.world_epoch = None
        self.generation = 0
        self.on_signal = lambda message: None
        self.on_gap = lambda: None

    def gap(self):
        self.generation += 1
        self.on_gap()
        for _, future in self.pending.values():
            if not future.done():
                future.set_result(None)

    async def listen(self):
        while True:
            try:
                async with aiomqtt.Client(**self.options, timeout=self.timeout) as client:
                    await client.subscribe(f"{self.prefix}/reply/{self.hub_id}/+", qos=1)
                    await client.subscribe(f"{self.prefix}/events", qos=1)
                    await client.subscribe(f"{self.prefix}/availability", qos=1)
                    self.client = client
                    async for message in client.messages:
                        self.receive(message)
            except aiomqtt.MqttError:
                pass
            finally:
                self.client = None
                self.online = None
                self.gap()
            await asyncio.sleep(1)

    def receive(self, message):
        topic = str(message.topic)
        if message.qos != 1:
            return
        try:
            raw = json.loads(message.payload, parse_constant=reject_constant)
        except (ValueError, UnicodeError, TypeError, RecursionError):
            return
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            return

        if topic == f"{self.prefix}/availability":
            status, epoch = raw.get("status"), raw.get("world_epoch")
            if status in ("online", "offline") and isinstance(epoch, str) and epoch:
                online = status == "online"
                if epoch != self.world_epoch or (self.online is not False and not online):
                    self.gap()
                self.world_epoch, self.online = epoch, online
            return
        if message.retain:
            return
        if topic == f"{self.prefix}/events":
            self.on_signal(raw)
            return

        request_id = raw.get("request_id")
        if not isinstance(request_id, str) or request_id not in self.pending:
            return
        reply_to, future = self.pending[request_id]
        if topic == reply_to and not future.done():
            future.set_result(raw.get("data"))

    async def request(self, route, **fields):
        if self.client is None or self.online is False:
            return None
        request_id = identity("rq")
        reply_to = f"{self.prefix}/reply/{self.hub_id}/{request_id}"
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = (reply_to, future)
        body = {"schema": SCHEMA, "request_id": request_id, "reply_to": reply_to, **fields}
        try:
            async with asyncio.timeout(self.timeout):
                await self.client.publish(f"{self.prefix}/{route}", encode(body), qos=1, retain=False)
                return await future
        except (aiomqtt.MqttError, TimeoutError):
            return None
        finally:
            self.pending.pop(request_id, None)

    async def discover(self):
        data = await self.request("discover")
        if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
            return None
        discovered = {}
        for item in data["devices"]:
            try:
                commands = item["capabilities"]["commands"]
                properties = item["capabilities"]["properties"]
                local = item["local_operation_reporting"]
                assumption = item.get("assumption")
                target = item["target"]
                if not (
                    isinstance(target, str) and target
                    and isinstance(item["device_type"], str)
                    and type(item["available"]) is bool
                    and type(local) is bool
                    and (not local or isinstance(assumption, str) and assumption)
                    and isinstance(commands, list) and all(isinstance(value, str) for value in commands)
                    and isinstance(properties, list) and all(isinstance(value, str) for value in properties)
                ):
                    continue
                discovered[target] = Capability(
                    item["device_type"], Substrate(item["substrate"]).value,
                    frozenset(commands), frozenset(properties), local, assumption if local else None,
                )
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
        return discovered

    async def read(self, target):
        observation = report(await self.request("read", target=target))
        return observation if observation and observation["target"] == target else None

    async def command(self, target, operation, desired, expected):
        data = await self.request(
            "command", target=target, operation_id=operation, desired=desired, expected=expected,
        )
        if (
            isinstance(data, dict) and data.get("operation_id") == operation
            and data.get("status") in tuple(ACK_STATUSES) and "job_id" in data
            and optional_id(data["job_id"])
            and (data["status"] == "ACCEPTED" or data["job_id"] is None)
        ):
            return {key: data[key] for key in ("status", "operation_id", "job_id")}
        return None


def reject_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")
