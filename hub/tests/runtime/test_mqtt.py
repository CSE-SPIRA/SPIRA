"""Send the fake World through a real broker when Mosquitto is installed."""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time

import aiomqtt
import pytest

from hub.spira_hub.device import SCHEMA

from .peers import Clock, Scenario, Stub, task
from .test_acceptance import install_light


def test_mqtt_discovery_command_signal_and_read_back(tmp_path):
    binary = shutil.which("mosquitto") or "/opt/homebrew/sbin/mosquitto"
    if not os.path.isfile(binary):
        pytest.skip("Mosquitto is unavailable")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    async def exercise():
        clock = Clock()
        stub = Stub(clock, task(clock))
        hub = Scenario(tmp_path, clock, stub=stub, real_mqtt=port)
        install_light(hub)
        hub.boot()
        pending = []

        def emit(topic, body, *, retain=False):
            pending.append((topic, body, retain))

        hub.world.emit = emit
        async with aiomqtt.Client("127.0.0.1", port) as simulator:
            for route in ("discover", "read", "command"):
                await simulator.subscribe(f"{hub.mqtt.prefix}/{route}", qos=1)
            await simulator.publish(f"{hub.mqtt.prefix}/availability", json.dumps({
                "schema": SCHEMA, "status": "online", "world_epoch": "we_fake",
            }), qos=1, retain=True)

            async def peer():
                async for message in simulator.messages:
                    await hub.world.publish(str(message.topic), message.payload,
                                            qos=message.qos, retain=message.retain)
                    while pending:
                        topic, body, retain = pending.pop(0)
                        await simulator.publish(f"{hub.mqtt.prefix}/{topic}", json.dumps(body),
                                                qos=1, retain=retain)

            tasks = [asyncio.create_task(hub.mqtt.listen()), asyncio.create_task(peer())]
            try:
                async with asyncio.timeout(4):
                    while hub.mqtt.online is not True:
                        assert not any(worker.done() for worker in tasks)
                        await asyncio.sleep(0.01)
                    await hub.reconcile()
                    await hub.cycle()
                assert len(hub.world.commands) == 1
                assert stub.executions[0]["status"] == "completed"
                assert stub.events[0]["payload"]["by"] == "spira"
            finally:
                for work in tasks:
                    work.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await hub.close()

    with subprocess.Popen([binary, "-p", str(port)], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL) as broker:
        try:
            for _ in range(50):
                assert broker.poll() is None
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except ConnectionRefusedError:
                    time.sleep(0.02)
            else:
                pytest.fail("Mosquitto did not open its test port")
            asyncio.run(exercise())
        finally:
            broker.terminate()
