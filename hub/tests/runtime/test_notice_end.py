"""HUB-AT23: end a verified fridge notice through the device and C-4 ports."""

import asyncio

import pytest

from .peers import Clock, Scenario, Stub, fixture

FRIDGE = "fridge_01"
TARGET = "mqtt:fridge_01"


@pytest.mark.parametrize("end_by,readback", [
    ("door", True), ("fallback", True), ("door", False),
])
def test_hub_at23_notice_end(tmp_path, end_by, readback):
    async def exercise():
        clock = Clock()
        line = fixture("plan.v1.json", "ep_9150")["tasks"][0]
        line["end"].update(after="2m", or_after="10m")
        stub = Stub(clock, line)
        hub = Scenario(tmp_path, clock, stub=stub)
        fridge = next(device for device in fixture("devices.json")["devices"] if device["id"] == FRIDGE)
        hub.write([fridge], {FRIDGE: {"target": TARGET, "commands": {"show_notice": "show_notice"}}})
        hub.world.add(TARGET, "fridge", {"show_notice": None}, ["show_notice", "clear_notice"])
        hub.boot()
        await hub.reconcile()
        hub.world.signal("fridge.door_opened", TARGET)
        await hub.cycle()
        assert hub.world.commands == []
        released = clock.advance(minutes=1)
        if end_by == "door":
            clock.advance(minutes=1)
            # This event arrives after package release but before its plan version.
            hub.world.signal("fridge.door_opened", TARGET)
        line["trigger"].update(released=True, at=released)
        stub.advance(line)
        await hub.reconcile()
        await hub.cycle()
        notice = line["actions"][0]["value"]
        assert hub.world.native[TARGET].values == {"show_notice": notice}
        if end_by == "door":
            clock.advance(minutes=1)
            hub.world.signal("fridge.door_opened", TARGET)
            hub.world.signal("fridge.door_opened", "mqtt:another_fridge")
            await hub.cycle()
            assert len(hub.world.commands) == 1
            clock.advance(minutes=1)
        else:
            clock.advance(minutes=9, seconds=59)
            await hub.cycle()
            assert len(hub.world.commands) == 1
            clock.advance(seconds=1)

        if not readback:
            hub.world.on_read = lambda _request, data: (
                dict(data, values={}, revisions={}) if len(hub.world.commands) == 2 else data
            )
        await hub.cycle()
        assert [entry["desired"] for entry in hub.world.commands] == [
            {"show_notice": notice}, {"show_notice": None},
        ]
        assert hub.world.native[TARGET].values == {"show_notice": None}
        shown, cleared = stub.executions
        assert (shown["cmd"], shown["status"]) == ("show_notice", "completed")
        assert cleared["kind"] == "run" and cleared["cmd"] == "clear_notice"
        assert cleared["task_id"] == line["task_id"]
        assert cleared["operation_id"] == hub.world.commands[-1]["operation_id"]
        assert cleared["status"] == ("completed" if readback else "unverifiable")
        assert cleared["observed"] == ({"show_notice": None} if readback else {})

        await hub.shutdown()
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        assert len(hub.world.commands) == len(stub.executions) == 2
        await hub.close()

    asyncio.run(exercise())
