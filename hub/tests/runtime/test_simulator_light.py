import asyncio
from contextlib import closing
from types import SimpleNamespace

from simulator.spira_simulator.mqtt import DeviceProtocol
from simulator.spira_simulator.profile import load_profile
from simulator.spira_simulator.world import World

from .peers import Clock, Scenario
from .test_acceptance import INSTALLATION


def test_hb_at_4_simulator_light_change_is_reported_and_preserved(tmp_path):
    async def exercise():
        clock = Clock("2026-10-17T13:40:00+09:00")
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        hub.path.write_bytes(INSTALLATION.read_bytes())
        hub.boot()

        def receive(topic, payload, *, qos, retain):
            hub.mqtt.receive(SimpleNamespace(topic=topic, payload=payload.encode(), qos=qos, retain=retain))

        try:
            world = World(tmp_path / "world.sqlite3", load_profile(), clock)
            with closing(world.store):
                protocol = DeviceProtocol(world, hub.mqtt.prefix, receive)

                async def publish(topic, payload, *, qos, retain):
                    protocol.receive(topic, payload, qos=qos, retained=retain)

                hub.mqtt.client = SimpleNamespace(publish=publish)
                await hub.reconcile()
                protocol.dispatch(world.home_event, "guests_arrive")
                await hub.cycle()

                light = "mqtt:light_01"
                prepared = world.read(light)["values"]["color"]
                assert prepared == {"hue": 330, "saturation": 45, "brightness": 70}
                world.mark_commands()
                clock.advance(minutes=10)
                chosen = {"kelvin": 2700}
                protocol.dispatch(world.local_change, light, "resident", {"color": chosen})
                await hub.cycle()

                receipts = await hub.receipts()
                changes = [event["payload"] for batch in receipts["events"] for event in batch
                           if event["type"] == "light.changed" and event["source"] == "light_01"]
                assert changes[-1] == {"property": "color", "from": prepared, "to": chosen, "by": "user"}

                clock.advance(minutes=30)
                protocol.dispatch(world.home_event, "event_end")
                await hub.cycle()
                (restore,) = [result for result in (await hub.receipts())["executions"]
                              if result["kind"] == "restore" and result["task_id"] == "t_mood#3"]
                assert {item["device"]: item["status"] for item in restore["items"]} == {
                    "display_01": "restored", "light_01": "skipped_user_changed",
                }
                assert world.read(light)["values"]["color"] == chosen
                assert world.command_counts()["by_device"]["light_01"]["other_commands"] == 0
        finally:
            await hub.close()

    asyncio.run(exercise())
