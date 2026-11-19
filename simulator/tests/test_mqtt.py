import json
import shutil
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from threading import Event
from uuid import uuid4

import paho.mqtt.client as mqtt
import pytest
from conftest import LIGHT, PREFIX
from fastapi.testclient import TestClient
from spira_simulator.api import create_app
from spira_simulator.world import DEVICE_SCHEMA


def test_protocol_rejects_retained_requests_and_foreign_reply_topics(wire):
    envelope = {
        "schema": DEVICE_SCHEMA,
        "request_id": "rq_01",
        "reply_to": f"{PREFIX}/reply/hub/rq_01",
        "operation_id": "op_01",
        "target": LIGHT,
        "desired": {"power": False},
    }
    for message, qos, retained in [
        (envelope, 1, True),
        (envelope, 0, False),
        ({**envelope, "reply_to": "unrelated/topic"}, 1, False),
        ({**envelope, "reply_to": f"{PREFIX}/reply/hub/rq_different"}, 1, False),
        ({**envelope, "reply_to": f"{PREFIX}/reply/+/rq_01"}, 1, False),
    ]:
        wire.protocol.receive(
            f"{PREFIX}/command",
            json.dumps(message).encode(),
            qos=qos,
            retained=retained,
        )
    assert wire.frames == []
    assert wire.read(LIGHT)["values"]["power"] is True


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.025)
    pytest.fail("process did not reach the expected state")


@contextmanager
def mosquitto(binary, port):
    process = subprocess.Popen(
        [binary, "-p", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    def listening():
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            return False

    try:
        wait_until(listening)
        yield
    finally:
        process.terminate()
        process.wait(timeout=5)


@contextmanager
def mqtt_peer(port):
    frames = Queue()
    subscribed = Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    client.on_connect = lambda conn, *_: conn.subscribe(
        [
            (f"{PREFIX}/reply/#", 1),
            (f"{PREFIX}/events", 1),
            (f"{PREFIX}/availability", 1),
        ]
    )
    client.on_subscribe = lambda *_: subscribed.set()
    client.on_message = lambda _c, _u, msg: frames.put(
        (msg.topic, json.loads(msg.payload), msg.qos, msg.retain)
    )
    client.connect("127.0.0.1", port)
    client.loop_start()
    try:
        assert subscribed.wait(5)
        yield client, frames
    finally:
        client.disconnect()
        client.loop_stop()


def test_mosquitto_requests_signals_availability_and_reconnect(tmp_path, monkeypatch):
    binary = shutil.which("mosquitto")
    if not binary and Path("/opt/homebrew/sbin/mosquitto").exists():
        binary = "/opt/homebrew/sbin/mosquitto"
    if not binary:
        pytest.skip("Mosquitto is required for the real MQTT transport check")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("MQTT_PREFIX", PREFIX)
    monkeypatch.setenv("MQTT_HOST", "127.0.0.1")
    monkeypatch.setenv("MQTT_PORT", str(port))

    auth = ("operator", uuid4().hex)
    with TestClient(
        create_app(tmp_path / "world.db", operator_enabled=True, operator_token=auth[1])
    ) as http:
        with mosquitto(binary, port):
            wait_until(lambda: http.get("/health").json()["mqtt"]["connected"])

            with mqtt_peer(port) as (peer, frames):

                def send(kind, request_id, retain=False, **body):
                    envelope = {
                        "schema": DEVICE_SCHEMA,
                        "request_id": request_id,
                        "reply_to": f"{PREFIX}/reply/hub/{request_id}",
                        **body,
                    }
                    peer.publish(
                        f"{PREFIX}/{kind}", json.dumps(envelope), qos=1, retain=retain
                    ).wait_for_publish(4)

                topic, online, qos, retained = frames.get(timeout=5)
                assert (topic, qos, retained) == (f"{PREFIX}/availability", 1, True)
                assert (
                    online["status"] == "online" and online["schema"] == DEVICE_SCHEMA
                )

                send("discover", "rq_discover")
                _, response, _, _ = frames.get(timeout=5)
                assert len(response["data"]["devices"]) == 7

                send(
                    "command",
                    "rq_retained",
                    True,
                    target=LIGHT,
                    operation_id="op_retained",
                    desired={"power": False},
                )
                send("read", "rq_initial", target=LIGHT)
                _, response, _, _ = frames.get(timeout=5)
                assert (
                    response["request_id"] == "rq_initial"
                    and response["data"]["values"]["power"]
                )

                send(
                    "command",
                    "rq_command",
                    target=LIGHT,
                    operation_id="op_real_broker",
                    desired={"power": False},
                )
                topic, response, qos, retained = frames.get(timeout=5)
                assert (topic, qos, retained) == (
                    f"{PREFIX}/reply/hub/rq_command",
                    1,
                    False,
                )
                assert response["data"]["status"] == "ACCEPTED"
                topic, event, qos, retained = frames.get(timeout=5)
                assert (topic, qos, retained) == (f"{PREFIX}/events", 1, False)
                assert (
                    not event["values"]["power"]
                    and event["operation_id"] == "op_real_broker"
                )

                send("read", "rq_read", target=LIGHT)
                _, response, _, _ = frames.get(timeout=5)
                assert (
                    not response["data"]["values"]["power"]
                    and response["data"]["operation_id"] is None
                )

        wait_until(lambda: not http.get("/health").json()["mqtt"]["connected"])
        prior_gap = http.get("/health").json()["mqtt"]["last_gap_at"]
        assert prior_gap
        assert (
            http.post(
                "/operator/device",
                auth=auth,
                json={
                    "target": LIGHT,
                    "actor": "resident",
                    "values": {"power": True},
                },
            ).status_code
            == 200
        )
        with mosquitto(binary, port):
            wait_until(lambda: http.get("/health").json()["mqtt"]["connected"])
            with mqtt_peer(port) as (peer, frames):
                _, online_again, _, _ = frames.get(timeout=5)
                assert online_again == online
                peer.publish(
                    f"{PREFIX}/read",
                    json.dumps(
                        {
                            "schema": DEVICE_SCHEMA,
                            "request_id": "rq_after_gap",
                            "reply_to": f"{PREFIX}/reply/hub/rq_after_gap",
                            "target": LIGHT,
                        }
                    ),
                    qos=1,
                ).wait_for_publish(4)
                topic, readback, _, _ = frames.get(timeout=5)
                assert topic == f"{PREFIX}/reply/hub/rq_after_gap"
                assert readback["data"]["values"]["power"]
                assert http.get("/health").json()["mqtt"]["last_gap_at"] >= prior_gap
