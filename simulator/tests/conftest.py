import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from spira_simulator.mqtt import DeviceProtocol
from spira_simulator.profile import load_profile
from spira_simulator.world import DEVICE_SCHEMA, World

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
PREFIX = "spira/test"
LIGHT = "mqtt:light_01"
CLEANER = "mqtt:cleaner_01"
OVEN = "mqtt:oven_01"
PLUG = "mqtt:plug_kettle"


def fixture_json(path):
    return json.loads((FIXTURES / path).read_text())


class Clock:
    def __init__(self):
        self.now = datetime.fromisoformat("2026-10-17T14:00:00+09:00")

    def __call__(self):
        return self.now

    def advance(self, seconds=1):
        self.now += timedelta(seconds=seconds)


class Wire:
    def __init__(self, world):
        self.frames = []
        self.protocol = DeviceProtocol(world, PREFIX, self.publish)

    def publish(self, topic, payload, *, qos, retain):
        self.frames.append((topic, json.loads(payload), qos, retain))

    def request(self, kind, **body):
        request_id = f"rq_{uuid4().hex}"
        reply_to = f"{PREFIX}/reply/test/{request_id}"
        start = len(self.frames)
        self.protocol.receive(
            f"{PREFIX}/{kind}",
            json.dumps(
                {
                    "schema": DEVICE_SCHEMA,
                    "request_id": request_id,
                    "reply_to": reply_to,
                    **body,
                }
            ).encode(),
            qos=1,
            retained=False,
        )
        first, *signals = self.frames[start:]
        assert first[0] == reply_to and first[1]["request_id"] == request_id
        assert first[1]["schema"] == DEVICE_SCHEMA and first[2:] == (1, False)
        return first[1]["data"], [frame[1] for frame in signals]

    def read(self, target):
        report, signals = self.request("read", target=target)
        assert not signals
        assert report["kind"] == "state_report" and report["event_type"] is None
        assert report["operation_id"] is None and report["local_operation"] is False
        return report

    def command(self, target, desired, operation_id=None, **args):
        return self.request(
            "command",
            target=target,
            desired=desired,
            operation_id=operation_id or f"op_{uuid4().hex}",
            **args,
        )


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def world(tmp_path, clock):
    world = World(tmp_path / "world.db", load_profile(), clock)
    try:
        yield world
    finally:
        world.store.close()


@pytest.fixture
def wire(world):
    return Wire(world)
