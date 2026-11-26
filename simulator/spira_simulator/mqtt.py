"""Translate spira.device.v1 MQTT messages without exposing World truth."""

import json
import logging
import re
from collections.abc import Callable
from threading import RLock

import paho.mqtt.client as mqtt
from paho.mqtt.subscribeoptions import SubscribeOptions

from .storage import encode
from .story_clock import ClockState
from .world import DEVICE_SCHEMA, World

log = logging.getLogger(__name__)
TOPIC_COMPONENT = re.compile(r"[^/+#\x00]+")


class DeviceProtocol:
    def __init__(self, world: World, prefix: str, publish: Callable):
        if any(not TOPIC_COMPONENT.fullmatch(part) for part in prefix.split("/")):
            raise ValueError("invalid MQTT prefix")
        self.world = world
        self.prefix = prefix
        self.publish = publish
        self.lock = RLock()

    def send(self, suffix: str, body: dict, *, retain: bool = False):
        return self.publish(
            f"{self.prefix}/{suffix}", encode(body), qos=1, retain=retain
        )

    def dispatch(self, action: Callable, *args, **kwargs):
        with self.lock:
            signals = action(*args, **kwargs)
            for signal in signals:
                self.send("events", signal)
            return signals

    def _reply_suffix(self, request_id, reply_to) -> str | None:
        if not isinstance(request_id, str) or not TOPIC_COMPONENT.fullmatch(request_id):
            return None
        stem = f"{self.prefix}/reply/"
        if not isinstance(reply_to, str) or not reply_to.startswith(stem):
            return None
        parts = reply_to[len(stem) :].split("/")
        if (
            len(parts) != 2
            or not TOPIC_COMPONENT.fullmatch(parts[0])
            or parts[1] != request_id
        ):
            return None
        return f"reply/{parts[0]}/{request_id}"

    def receive(self, topic: str, payload: bytes, *, qos: int, retained: bool):
        if qos != 1 or not topic.startswith(f"{self.prefix}/"):
            return
        request_kind = topic[len(self.prefix) + 1 :]
        if request_kind == "clock" and retained:
            try:
                state = ClockState.model_validate_json(payload) if payload else None
            except ValueError:
                return
            with self.lock:
                self.world.story_clock = state
            return
        if retained:
            return
        try:
            body = json.loads(payload)
        except (ValueError, RecursionError):
            return
        if not isinstance(body, dict) or body.get("schema") != DEVICE_SCHEMA:
            return
        request_id = body.get("request_id")
        reply_suffix = self._reply_suffix(request_id, body.get("reply_to"))
        if reply_suffix is None:
            return
        target = body.get("target")
        signals = []
        with self.lock:
            if request_kind == "discover":
                data = self.world.discover()
            elif request_kind == "read" and isinstance(target, str) and target:
                data = self.world.read(target)
            elif request_kind == "command" and isinstance(target, str) and target:
                operation = body.get("operation_id")
                desired = body.get("desired")
                expected = body.get("expected", {})
                if not isinstance(operation, str) or not operation:
                    return
                if not isinstance(desired, dict) or not isinstance(expected, dict):
                    return
                if not all(
                    isinstance(witness, str) and witness
                    for witness in expected.values()
                ):
                    return
                data, signals = self.world.command(operation, target, desired, expected)
            else:
                return
            self.send(
                reply_suffix,
                {"schema": DEVICE_SCHEMA, "request_id": request_id, "data": data},
            )
            for signal in signals:
                self.send("events", signal)


class Broker:
    def __init__(
        self,
        world: World,
        host: str,
        port: int,
        prefix: str,
        username=None,
        password=None,
    ):
        self.host = host
        self.port = port
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5
        )
        if username:
            self.client.username_pw_set(username, password)
        self.protocol = DeviceProtocol(world, prefix, self._publish)
        self.epoch = world.epoch
        self.connected = False
        self.ever_connected = False
        self.last_gap_at: str | None = None
        self.client.will_set(
            f"{prefix}/availability",
            encode(self._availability("offline")),
            qos=1,
            retain=True,
        )
        self.client.on_connect = self._connected
        self.client.on_disconnect = self._disconnected
        self.client.on_message = self._receive

    def _availability(self, status: str) -> dict:
        return {"schema": DEVICE_SCHEMA, "status": status, "world_epoch": self.epoch}

    def _publish(self, topic, payload, *, qos, retain):
        if self.connected:
            info = self.client.publish(topic, payload, qos=qos, retain=retain)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                self._gap()
            return info
        self._gap()
        return None

    def _gap(self):
        self.last_gap_at = self.protocol.world.clock().isoformat()

    def _connected(self, client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            return
        with self.protocol.lock:
            self.connected = True
            if self.ever_connected:
                self._gap()
                log.info("MQTT reconnected after an observation gap")
            self.ever_connected = True
            # Preserve the RETAIN bit for live messages and skip stored requests.
            subscriptions = [
                (
                    f"{self.protocol.prefix}/{kind}",
                    SubscribeOptions(qos=1, retainAsPublished=True, retainHandling=2),
                )
                for kind in ("discover", "read", "command")
            ]
            subscriptions.append((
                f"{self.protocol.prefix}/clock", SubscribeOptions(qos=1, retainAsPublished=True),
            ))
            client.subscribe(subscriptions)
            self.protocol.send(
                "availability", self._availability("online"), retain=True
            )

    def _disconnected(self, _client, _userdata, _flags, _reason, _properties):
        with self.protocol.lock:
            if self.connected:
                self._gap()
            self.connected = False

    def _receive(self, _client, _userdata, message):
        self.protocol.receive(
            message.topic, message.payload, qos=message.qos, retained=message.retain
        )

    def status(self) -> dict:
        with self.protocol.lock:
            return {"connected": self.connected, "last_gap_at": self.last_gap_at}

    def start(self):
        self.client.connect_async(self.host, self.port)
        self.client.loop_start()

    def close(self):
        with self.protocol.lock:
            pending = (
                self.protocol.send(
                    "availability", self._availability("offline"), retain=True
                )
                if self.connected
                else None
            )
        try:
            if pending and pending.rc == mqtt.MQTT_ERR_SUCCESS:
                pending.wait_for_publish(timeout=2)
        finally:
            self.client.disconnect()
            self.client.loop_stop()
