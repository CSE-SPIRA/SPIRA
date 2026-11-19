import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import httpx2 as httpx
import pytest
from spira_contracts.plan import Action

from hub.spira_hub.config import Installation
from hub.tests.fixture_server import create_app as fixture_app

from .peers import Clock, Scenario, Stub, action, fixture, light_config, task

INSTALLATION = Path(__file__).resolve().parents[2] / "installation.example.json"


def run(test):
    return asyncio.run(test())


def install_light(scenario, *, local=True, substrate="virtual", target="light"):
    device, binding, native = light_config(substrate=substrate, target=target)
    scenario.world.add(*native, local=local, substrate=substrate)
    scenario.write([device], {device["id"]: binding})
    return device, binding


def install_birthday(scenario):
    config = json.loads(INSTALLATION.read_text())
    initial = {
        "cleaner_01": {"clean": None, "in_use": False},
        "light_01": {"color": {"kelvin": 3000}},
        "display_01": {"play_mood": None},
        "cooktop_01": {"child_lock": False, "in_use": False},
        "oven_01": {"preset": None, "in_use": False},
        "fridge_01": {"show_notice": None},
        "plug_kettle": {"power": True},
    }
    for device in config["devices"]["devices"]:
        logical = device["id"]
        scenario.world.add(f"mqtt:{logical}", device["type"], initial[logical],
                           [command["cmd"] for command in device["commands"]],
                           local=logical in ("light_01", "oven_01"))
    scenario.path.write_text(json.dumps(config))


def guest(world, clock):
    world.signal("doorbell.pressed", "mqtt:sim_doorbell")
    clock.advance(seconds=1)
    world.signal("door_lock.opened", "mqtt:sim_door_lock")
    clock.advance(seconds=1)
    world.signal("presence.room_occupied", "mqtt:sim_presence")


def test_hub_at01_plan_floor_and_unchanged_actions(tmp_path):
    async def exercise():
        clock = Clock()
        line = task(clock)
        stub = Stub(clock, line)
        hub = Scenario(tmp_path, clock, stub=stub)
        install_light(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        assert len(hub.world.commands) == 1
        assert [item["plan_version"] for item in stub.acks] == [1]
        await hub.runtime.refresh()
        stub.plans[0]["tasks"] = [task(clock, n=2)]
        await hub.runtime.refresh()
        stub.plans[0]["plan_version"] = 1
        await hub.cycle()
        assert len(hub.world.commands) == 1
        stub.advance(line)
        await hub.runtime.refresh()
        stub.plans[0]["plan_version"] = 1
        await hub.runtime.refresh()
        await hub.cycle()
        assert [item["plan_version"] for item in stub.acks] == [1, 2]
        assert len(hub.world.commands) == 1
        assert [item["status"] for item in stub.executions] == ["completed"]
        await hub.close()
    run(exercise)


def test_hub_at02_partial_admission_open_type_and_offline(tmp_path):
    async def exercise():
        clock = Clock()
        due = clock.advance(minutes=1)
        valid = task(clock, trigger={"time": due})
        bad = task(clock, action(cmd="bogus"), n=2)
        malformed = task(clock, n=3)
        malformed["trigger"]["foreign"] = True
        novel = task(clock, action("speaker_01", "play", {"playlist": "family", "volume": 25}), n=4)
        offline = task(clock, action("light_02"), n=5)
        stub = Stub(clock, valid, bad, malformed, novel, offline)
        hub = Scenario(tmp_path, clock, stub=stub)
        light, binding, native = light_config()
        second, second_binding, second_native = light_config(target="off", logical="light_02")
        speaker = fixture("devices.json", "ep_9120")["devices"][1]
        hub.write([light, second, speaker], {"light_01": binding, "light_02": second_binding,
                  "speaker_01": {"target": "speaker", "commands": {"play": "mix"}}})
        hub.world.add(*native)
        hub.world.add(*second_native)
        hub.world.native["off"].available = False
        hub.world.add("speaker", "speaker", {"mix": None}, ["play"])
        hub.boot()
        await hub.reconcile()
        assert hub.world.commands == []
        assert stub.acks[-1]["rejected_tasks"] == [
            {"task_id": "t_test#2", "reason": "unsupported_cmd"},
            {"task_id": "t_test#3", "reason": "schema"},
        ]
        assert stub.registry["devices"][2]["type"] == "speaker"
        assert len((await hub.state())["waiting"]) == 3
        await hub.cycle()
        assert {item["device"]: item["reason"] or item["status"] for item in stub.executions} == {
            "light_01": "completed", "light_02": "offline", "speaker_01": "completed",
        }
        await hub.close()
    run(exercise)


def test_hub_at03_rebind_preserves_previous_and_replacement(tmp_path):
    async def exercise():
        clock = Clock()
        stub = Stub(clock, task(clock))
        hub = Scenario(tmp_path, clock, stub=stub)
        install_light(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        old_state = deepcopy(hub.world.native["light"].values)
        install_light(hub, target="replacement")
        await hub.reconcile()
        clock.advance(minutes=1)
        hub.world.signal("event_end", "home")
        await hub.cycle()
        assert len(hub.world.commands) == 1
        assert hub.world.native["light"].values == old_state
        assert hub.world.native["replacement"].values == {"color": {"kelvin": 3000}}
        assert stub.executions[-1]["items"] == [{"device": "light_01", "status": "unknown"}]
        assert (await hub.state())["commands"][0]["target"] == "light"
        await hub.close()
    run(exercise)


def test_hub_at04_source_order_window_restart_and_server_release(tmp_path):
    async def exercise():
        clock = Clock()
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        install_birthday(hub)
        hub.boot()
        guest(hub.world, clock)
        await hub.reconcile()
        assert (await hub.state())["server_peer"] == "SPIRA fixture - non-inference test support"
        await hub.cycle()
        assert {cmd["target"] for cmd in hub.world.commands} == {"mqtt:cleaner_01", "mqtt:cooktop_01", "mqtt:plug_kettle"}
        assert any(work["task_id"] == "t_mood#3" for work in (await hub.state())["waiting"])
        await hub.shutdown()
        hub.boot()
        await hub.reconcile()
        clock.advance(minutes=1)
        hub.world.signal("door_lock.opened", "mqtt:sim_door_lock")
        hub.world.signal("doorbell.pressed", "wrong")
        hub.world.signal("door_lock.opened", "mqtt:sim_door_lock")
        hub.world.signal("doorbell.pressed", "mqtt:sim_doorbell", at="2026-10-17T13:10:00+09:00")
        hub.world.signal("door_lock.opened", "mqtt:sim_door_lock", at="2026-10-17T13:11:00+09:00")
        hub.world.signal("presence.room_occupied", "mqtt:sim_presence")
        await hub.cycle()
        assert len(hub.world.commands) == 3
        guest(hub.world, clock)
        await hub.cycle()
        assert [command["target"] for command in hub.world.commands].count("mqtt:light_01") == 1
        assert all(command["target"] != "mqtt:fridge_01" for command in hub.world.commands)
        hub.world.signal("camera.package_removed", "wrong", removed_count=1)
        await hub.cycle()
        assert all(command["target"] != "mqtt:fridge_01" for command in hub.world.commands)
        hub.world.signal("camera.package_removed", "mqtt:sim_camera",
                                       removed_count=1, remaining_count=0)
        await hub.runtime.flush()
        packet = [row["packet"][0] for row in (await hub.state())["events"]
                  if row["packet"][0]["type"] == "package.brought_in"]
        assert len(packet) == 1 and packet[0]["payload"] == {"count": 1}
        # Fixture release is historical, so its 12h expiry prevents late display.
        await hub.cycle()
        assert all(command["target"] != "mqtt:fridge_01" for command in hub.world.commands)
        assert any(batch[0]["event_id"] == packet[0]["event_id"] for batch in (await hub.receipts())["events"])
        await hub.close()
    run(exercise)


@pytest.mark.parametrize("change,reason", [
    ("stop", "plan_cancelled"), ("pause", "paused"), ("revoke", "not_delegated"),
    ("outage", "plan_unconfirmed"), ("newer", None),
])
def test_hub_at05_final_authority_after_device_read(tmp_path, change, reason):
    async def exercise():
        clock = Clock()
        line = task(clock)
        stub = Stub(clock, line)
        hub = Scenario(tmp_path, clock, stub=stub)
        device, binding = install_light(hub)
        hub.boot()
        await hub.reconcile()

        async def delay(_):
            hub.world.before_read = None
            await asyncio.sleep(0)
            if change == "stop":
                stub.advance(cancelled=[{"task_id": line["task_id"], "restore": False}])
            elif change == "pause":
                stub.paused = True
            elif change == "revoke":
                device["commands"] = []
                binding["commands"] = {}
                hub.write([device], {"light_01": binding})
            elif change == "outage":
                stub.down = True
            else:
                stub.advance(task(clock, action(value={"hue": 0, "saturation": 0, "brightness": 37})))

        hub.world.before_read = delay
        await hub.cycle()
        assert hub.world.commands == []
        if reason:
            assert stub.executions[-1]["reason"] == reason
        else:
            await hub.cycle()
            assert hub.world.commands[0]["desired"]["color"]["brightness"] == 37
        await hub.close()
    run(exercise)


def test_hub_at06_ack_is_separate_until_fresh_matching_read_back(tmp_path):
    async def exercise():
        clock = Clock()
        stub = Stub(clock, task(clock))
        hub = Scenario(tmp_path, clock, stub=stub)
        install_light(hub)
        hub.boot()
        await hub.reconcile()
        seen = []

        def corrupt(_request, data):
            if not hub.world.commands:
                return data
            seen.append(data)
            match len(seen):
                case 1:
                    return dict(data, observed_at=(clock() - timedelta(seconds=5)).isoformat())
                case 2:
                    return None
                case 3:
                    return dict(data, values={})
                case 4:
                    return dict(data, operation_id="op_wrong")
                case 5:
                    return dict(data, available=False)
                case _:
                    return data

        hub.world.on_read = corrupt
        await hub.cycle()
        assert len(seen) == 6
        assert [item["status"] for item in stub.executions] == ["completed"]
        result = (await hub.state())["commands"][0]
        assert result["acknowledgement"]["status"] == "ACCEPTED"
        assert result["read_back"]["values"]["color"]["hue"] == 330
        await hub.close()
    run(exercise)


def test_hub_at08_and_at17_property_ownership_and_dashboard_provisional(tmp_path):
    async def exercise():
        clock = Clock()
        first, first_bind, first_native = light_config()
        second, second_bind, second_native = light_config(
            substrate="physical", target="other", logical="light_02",
        )
        display = fixture("devices.json")["devices"][2]
        line = task(clock, action(), action("light_02"), action("display_01", "play_mood", {"scene": "kids_party"}))
        waiting = task(clock, n=2, trigger={"event": "guest_arrived"})
        uncertain = task(clock, action("display_01", "play_mood", {"scene": "party"}), n=3)
        stub = Stub(clock, line, waiting, uncertain)
        hub = Scenario(tmp_path, clock, stub=stub)
        hub.world.add(*first_native, local=True)
        hub.world.add(*second_native, substrate="physical")
        hub.world.add("display", "display", {"scene": None}, ["play_mood", "off"])
        hub.write([first, second, display], {"light_01": first_bind, "light_02": second_bind,
                   "display_01": {"target": "display", "commands": {"play_mood": "scene"}}})
        hub.boot()
        await hub.reconcile()

        async def resist(command):
            hub.world.unchanged = command["desired"] == {"scene": {"scene": "party"}}

        hub.world.before_command = resist
        await hub.cycle()
        assert "unverifiable" in [row["status"] for row in stub.executions]
        desired = deepcopy(hub.world.native["other"].values)
        clock.advance(seconds=1)
        hub.world.change("light", {"color": {"kelvin": 2700}}, local=True)
        hub.world.change("other", {"color": {"kelvin": 6500}})
        hub.world.change("other", desired)
        clock.advance(minutes=10)
        hub.world.signal("event_end", "home")
        await hub.cycle()
        assert hub.world.native["light"].values == {"color": {"kelvin": 2700}}
        assert hub.world.native["other"].values == desired
        assert hub.world.native["display"].values == {"scene": None}
        state = await hub.state()
        by = [item["packet"][0]["payload"].get("by") for item in state["events"] if item["delivered"]]
        assert "user" in by and "unknown" in by and "spira" in by
        page = (await hub.dashboard.get("/")).text
        order = [page.index(title) for title in ("Waiting work", "Command acknowledgement and read-back",
                 "Person actions and C-3 events", "Restoration and skips")]
        assert order == sorted(order)
        assert all(label in page for label in ("Class A assumption", "virtual", "physical", "ACCEPTED",
                   "unverifiable", "skipped_user_changed", "restored", "Received by Server", "C-3 payload"))
        assert "actor" not in page and "ground_truth_actor" not in page
        await hub.close()
    run(exercise)


def test_hub_at04_fixture_package_release_runs_only_after_higher_version(tmp_path):
    async def exercise():
        clock = Clock("2026-10-16T17:55:00+09:00")
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        assert hub.world.commands == []
        assert (await hub.state())["waiting"][-1]["plan_version"] == 1
        clock.advance(minutes=11)
        hub.world.signal("camera.package_removed", "wrong", removed_count=1)
        await hub.cycle()
        assert hub.world.commands == []
        brought_in = hub.world.signal("camera.package_removed", "mqtt:sim_camera",
                                       removed_count=1, remaining_count=0)
        hub.world.emit("events", brought_in)
        await hub.runtime.flush()
        await hub.cycle()
        assert [cmd["target"] for cmd in hub.world.commands] == ["mqtt:fridge_01", "mqtt:fridge_01"]
        receipts = await hub.receipts()
        assert sum(batch[0]["type"] == "package.brought_in" for batch in receipts["events"]) == 1
        assert {result["plan_version"] for result in receipts["executions"]} == {2}
        assert {result["status"] for result in receipts["executions"]} == {"completed"}
        assert [cmd["desired"] for cmd in hub.world.commands] == [
            {"show_notice": line["actions"][0]["value"]}
            for line in fixture("plan.v3.json")["tasks"] if line["source"] == "item"
        ]
        hub.world.signal("fridge.door_opened", "mqtt:fridge_01")
        await hub.cycle()
        fridge_event = (await hub.receipts())["events"][-1][0]
        assert {key: value for key, value in fridge_event.items() if key != "event_id"} == {
            "household_id": "h_042", "type": "fridge.door_opened", "source": "fridge_01",
            "at": clock().isoformat(), "payload": {"by": "unknown"},
        }
        await hub.close()
    run(exercise)


def test_hub_at05_no_quiet_hours_gate_and_same_job_completion(tmp_path):
    async def exercise():
        clock = Clock("2026-10-17T02:00:00+09:00")
        line = task(clock, action("cleaner_01", "clean", {"room": "거실"}), restore=False)
        stub = Stub(clock, line)
        hub = Scenario(tmp_path, clock, stub=stub)
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        assert [item["status"] for item in stub.executions] == ["running"]
        job_id = hub.world.native["mqtt:cleaner_01"].job_id
        assert job_id is not None
        clock.advance(minutes=3)
        hub.world.change("mqtt:cleaner_01", {"in_use": False}, event="cleaner.completed", job=job_id)
        await hub.cycle()
        assert [item["status"] for item in stub.executions] == ["running", "completed"]
        assert len({item["operation_id"] for item in stub.executions}) == 1
        assert [event["payload"]["by"] for event in stub.events] == ["spira", "unknown"]
        await hub.close()
    run(exercise)


def test_hub_at07_person_and_replacement_jobs_preserved_provisional(tmp_path):
    async def exercise():
        clock = Clock()
        oven = action("oven_01", "set_cook_standby", {"temp_c": 170, "minutes": 20})
        stub = Stub(clock, task(clock, oven))
        hub = Scenario(tmp_path, clock, stub=stub)
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        assert hub.world.native["mqtt:oven_01"].values["preset"] == oven["value"]
        clock.advance(minutes=1)
        hub.world.change("mqtt:oven_01", {"in_use": True}, event="oven.started", local=True, job="job_person")
        stub.advance(task(clock, oven), task(clock, oven, n=2))
        await hub.reconcile()
        await hub.cycle()
        assert stub.executions[-1]["reason"] == "in_use_by_person"
        clock.advance(minutes=1)
        hub.world.change("mqtt:oven_01", {"in_use": True}, event="oven.started", job="job_foreign")
        hub.world.signal("presence.room_empty", "mqtt:sim_presence")
        await hub.cycle()
        assert len(hub.world.commands) == 1
        assert hub.world.native["mqtt:oven_01"].job_id == "job_foreign"
        assert [event["payload"]["by"] for event in stub.events if event["type"] == "oven.started"] == [
            "user", "unknown",
        ]
        assert stub.executions[-1]["items"] == [{"device": "oven_01", "status": "skipped_user_changed"}]
        await hub.close()
    run(exercise)


def test_hub_at09_dispatch_crash_and_byte_stable_resend(tmp_path):
    async def exercise():
        clock = Clock()
        stub = Stub(clock, task(clock), task(clock, action("light_02"), n=2, trigger={
            "time": (clock() + timedelta(minutes=1)).isoformat(),
        }))
        hub = Scenario(tmp_path, clock, stub=stub)
        first, binding, native = light_config()
        other, other_binding, other_native = light_config(logical="light_02", target="other")
        hub.world.add(*native)
        hub.world.add(*other_native)
        hub.write([first, other], {"light_01": binding, "light_02": other_binding})
        hub.boot()
        await hub.reconcile()
        stub.reject_delivery = True
        await hub.cycle()
        assert len(stub.packets) == 2
        originals = stub.packets.copy()

        can_crash = asyncio.Event()
        keep_waiting = asyncio.Event()
        async def crash_after_effect(body):
            hub.world.apply(body)
            can_crash.set()
            await keep_waiting.wait()

        hub.world.before_command = crash_after_effect
        clock.advance(minutes=1)
        dispatch = asyncio.create_task(hub.runtime.step())
        await can_crash.wait()
        assert hub.world.native["other"].values["color"]["hue"] == 330
        dispatch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await dispatch
        hub.world.before_command = None
        await hub.shutdown()
        hub.boot()
        stub.reject_delivery = False
        await hub.reconcile()
        await hub.cycle()
        assert len(hub.world.commands) == 2
        assert all(stub.packets.count(body) == 2 for body in originals)
        recovered = next(row for row in stub.executions if row["device"] == "light_02")
        assert recovered["status"] == "unknown"
        assert (await hub.state())["commands"][0]["acknowledgement"] is None
        clock.advance(minutes=1)
        hub.world.signal("event_end", "home")
        await hub.cycle()
        assert hub.world.native["light"].values == {"color": {"kelvin": 3000}}
        assert hub.world.native["other"].values["color"]["hue"] == 330
        await hub.close()
    run(exercise)


def test_hub_at12_fixture_stop_restores_owned_effects_immediately(tmp_path):
    async def exercise():
        clock = Clock()
        due = (clock() + timedelta(minutes=35)).isoformat()
        other_card = task(clock, action("light_01", "color_temp", {"kelvin": 3200}),
                          trigger={"time": due})
        extra = Stub(clock, other_card)
        fixture_transport = httpx.ASGITransport(app=fixture_app("ep_9031"))

        async def respond(request):
            route = request.url.path
            if (route == "/v1/hub/plans/ep_test/ack"
                    or (route == "/v1/hub/executions" and json.loads(request.content)["plan_id"] == "ep_test")):
                return await extra.respond(request)
            response = await fixture_transport.handle_async_request(request)
            if route != "/v1/hub/plans":
                return response
            await response.aread()
            body = response.json()
            body["plans"].extend(extra.plans)
            return httpx.Response(200, json=body, headers={
                "X-SPIRA-Fixture": response.headers["X-SPIRA-Fixture"],
            })

        hub = Scenario(tmp_path, clock, episode="ep_9031", transport=httpx.MockTransport(respond))
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        line_off = await hub.http.post("/v1/cards/nc_331/reactions", json=fixture("reactions.json")[0])
        assert line_off.status_code == 200
        await hub.runtime.refresh()
        guest(hub.world, clock)
        await hub.cycle()
        display = hub.world.native["mqtt:display_01"]
        light = hub.world.native["mqtt:light_01"]
        oven = hub.world.native["mqtt:oven_01"]
        cooktop = hub.world.native["mqtt:cooktop_01"]
        kettle = hub.world.native["mqtt:plug_kettle"]
        assert display.values["play_mood"] == {"scene": "kids_party"}
        assert cooktop.values["child_lock"] is True and kettle.values["power"] is False
        clock.advance(minutes=1)
        hub.world.change("mqtt:light_01", {"color": {"kelvin": 2700}}, local=True)
        hub.world.change("mqtt:oven_01", {"in_use": True}, local=True,
                         event="oven.started", job="job_person")
        stop = await hub.http.post("/v1/cards/nc_331/reactions", json={"reaction": "stop"})
        assert stop.status_code == 200 and stop.json()["stopped"]
        await hub.reconcile()
        await hub.cycle()

        assert (await hub.dashboard.post("/stop")).status_code == 404
        assert (await hub.dashboard.post("/stop-all")).status_code == 404
        assert display.values["play_mood"] is None
        assert light.values == {"color": {"kelvin": 2700}}
        assert cooktop.values["child_lock"] is False and kettle.values["power"] is True
        assert oven.job_id == "job_person" and oven.values["preset"] is None
        assert {row["task_id"] for row in (await hub.state())["waiting"]} == {
            "t_fridge#5", "t_fridge#6", other_card["task_id"],
        }
        receipts = await hub.receipts()
        assert not any(event["type"] == "event_end" for batch in receipts["events"] for event in batch)
        restores = {
            row["task_id"]: {item["device"]: item["status"] for item in row["items"]}
            for row in receipts["executions"] if row["kind"] == "restore"
        }
        assert restores == {
            "t_safe#2": {"cooktop_01": "restored", "plug_kettle": "restored"},
            "t_mood#3": {"display_01": "restored", "light_01": "skipped_user_changed"},
        }
        clock.advance(minutes=35)
        await hub.cycle()
        assert light.values == {"color": {"kelvin": 3200}}
        assert oven.job_id == "job_person" and oven.values["preset"] is None
        assert extra.executions[0]["status"] == "completed"
        await hub.close()
    run(exercise)


def test_running_cleaner_line_off_uses_conditional_stop(tmp_path):
    async def exercise():
        clock = Clock()
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        cleaner = hub.world.native["mqtt:cleaner_01"]
        assert cleaner.job_id and cleaner.values["in_use"]
        witness = cleaner.revisions["clean"]
        line_off = await hub.http.post("/v1/cards/nc_331/reactions", json=fixture("reactions.json")[0])
        assert line_off.status_code == 200
        await hub.reconcile()
        await hub.cycle()
        run_command, stop = [cmd for cmd in hub.world.commands if cmd["target"] == "mqtt:cleaner_01"]
        assert run_command["desired"] == {"clean": {"room": "거실"}}
        assert stop["desired"] == {"clean": None} and stop["expected"]["clean"] == witness
        assert cleaner.job_id is None and not cleaner.values["in_use"]
        restores = [row for row in (await hub.receipts())["executions"] if row["kind"] == "restore"]
        assert [row["items"] for row in restores] == [[{"device": "cleaner_01", "status": "restored"}]]
        await hub.close()
    run(exercise)


@pytest.mark.parametrize("with_sensors", [False, True])
def test_hub_at15_fixture_receipts_keep_attribution_provisional(tmp_path, with_sensors):
    async def exercise():
        clock = Clock()
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        install_birthday(hub)
        device = hub.world.native["mqtt:light_01"]
        device.spec = {**device.spec}
        hub.boot()
        await hub.reconcile()
        guest(hub.world, clock)
        await hub.cycle()
        for index, label in enumerate(("class_a", "class_b", "automation", "device")):
            clock.advance(seconds=1)
            if with_sensors:
                hub.world.signal("doorbell.pressed", "mqtt:sim_doorbell")
                hub.world.signal("door_lock.opened", "mqtt:sim_door_lock")
            if label == "class_b":
                device.spec.update(local_operation_reporting=False)
                await hub.runtime.discover()
            hub.world.change("mqtt:light_01", {"color": {"kelvin": 2730 + index}},
                             local=label == "class_a")
            if with_sensors:
                hub.world.signal("presence.room_occupied", "mqtt:sim_presence")
        await hub.cycle()
        receipts = await hub.receipts()
        actual = [event for batch in receipts["events"] for event in batch
                  if event["source"] == "light_01" and event["type"] == "light.changed"]
        assert [event["payload"]["by"] for event in actual] == ["spira", "user", "unknown", "unknown", "unknown"]
        assert len({event["event_id"] for event in actual}) == 5
        await hub.close()
    run(exercise)


@pytest.mark.parametrize("observed_end", [True, False], ids=["observed_end", "time_fallback"])
def test_hub_at16_fixture_protective_release(tmp_path, observed_end):
    async def exercise():
        clock = Clock()
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        guest(hub.world, clock)
        await hub.cycle()

        display = hub.world.native["mqtt:display_01"]
        light = hub.world.native["mqtt:light_01"]
        cooktop = hub.world.native["mqtt:cooktop_01"]
        kettle = hub.world.native["mqtt:plug_kettle"]
        assert display.values["play_mood"] == {"scene": "kids_party"}
        assert light.values["color"] == {"hue": 330, "saturation": 45, "brightness": 70}
        assert cooktop.values["child_lock"] is True and kettle.values["power"] is False
        before = len(hub.world.commands)
        if observed_end:
            clock.advance(minutes=5)
            hub.world.signal("presence.room_empty", "wrong")
            await hub.cycle()
            assert len(hub.world.commands) == before
            hub.world.signal("presence.room_empty", "mqtt:sim_presence")
        else:
            clock.advance(hours=7)
        await hub.cycle()

        assert display.values["play_mood"] is None
        assert light.values["color"] == {"kelvin": 3000}
        assert cooktop.values["child_lock"] is (not observed_end)
        assert kettle.values["power"] is observed_end
        changes = {cmd["target"]: cmd["desired"] for cmd in hub.world.commands[before:]}
        assert changes == {
            "mqtt:display_01": {"play_mood": None},
            "mqtt:light_01": {"color": {"kelvin": 3000}},
            **({"mqtt:cooktop_01": {"child_lock": False}, "mqtt:plug_kettle": {"power": True}}
               if observed_end else {}),
        }
        receipts = await hub.receipts()
        release_status = "restored" if observed_end else "withheld_end_not_observed"
        assert {
            row["task_id"]: {item["device"]: item["status"] for item in row["items"]}
            for row in receipts["executions"] if row["kind"] == "restore"
        } == {
            "t_safe#2": {"cooktop_01": release_status, "plug_kettle": release_status},
            "t_mood#3": {"display_01": "restored", "light_01": "restored"},
        }
        assert release_status in (await hub.dashboard.get("/")).text
        assert sum(event["type"] == "event_end" for batch in receipts["events"] for event in batch) == observed_end
        await hub.cycle()
        assert await hub.receipts() == receipts
        await hub.close()
    run(exercise)


def test_oven_standby_time_fallback_relinquishes_without_restoring(tmp_path):
    async def exercise():
        clock = Clock()
        preset = {"temp_c": 170, "minutes": 20}
        deadline = (clock() + timedelta(minutes=1)).isoformat()
        line = task(clock, action("oven_01", "set_cook_standby", preset), end={
            "on": "oven.started", "by": "user", "or_time": deadline, "restore": False,
        })
        line["way"] = "standby"
        stub = Stub(clock, line)
        hub = Scenario(tmp_path, clock, stub=stub)
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()

        oven = hub.world.native["mqtt:oven_01"]
        assert oven.values["preset"] == preset
        assert len(hub.world.commands) == 1
        assert [(row["kind"], row["status"]) for row in stub.executions] == [("run", "completed")]
        assert stub.executions[0]["observed"]["preset"] == preset
        executions, events = stub.executions.copy(), stub.events.copy()

        clock.advance(minutes=1)
        await hub.cycle()
        assert oven.values["preset"] == preset
        assert len(hub.world.commands) == 1
        assert stub.executions == executions
        assert stub.events == events

        # A later cancellation cannot reopen the ended lifecycle to restore the preset.
        stub.advance(cancelled=[{"task_id": line["task_id"], "restore": True}])
        await hub.reconcile()
        await hub.cycle()
        assert stub.acks[-1]["plan_version"] == 2
        assert oven.values["preset"] == preset
        assert len(hub.world.commands) == 1
        assert stub.executions == executions
        await hub.close()
    run(exercise)


def test_protective_end_delay_outlasts_fallback_if_event_was_observed(tmp_path):
    async def exercise():
        clock = Clock()
        line = task(clock, end={"on": "event_end", "after": "2m", "or_after": "2m", "restore": True})
        line["protective"] = True
        stub = Stub(clock, line)
        hub = Scenario(tmp_path, clock, stub=stub)
        install_light(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        clock.advance(minutes=1)
        hub.world.signal("event_end", "home")
        clock.advance(minutes=1)
        await hub.cycle()
        assert len(hub.world.commands) == 1
        assert [result["kind"] for result in stub.executions] == ["run"]
        clock.advance(minutes=1)
        await hub.cycle()
        assert hub.world.native["light"].values == {"color": {"kelvin": 3000}}
        assert stub.executions[-1]["items"] == [{"device": "light_01", "status": "restored"}]
        await hub.close()
    run(exercise)


def test_relative_fallback_uses_only_flag_and_keeps_explicit_release_authority(tmp_path):
    async def exercise():
        clock = Clock()
        end = {"on": "event_end", "or_after": "1m", "restore": True}
        protected = task(clock, end=end)
        protected["protective"] = True
        ordinary = task(clock, action("cooktop_01", "child_lock"), n=2, end=end)
        ordinary["protective"] = False
        stub = Stub(clock, protected, ordinary)
        hub = Scenario(tmp_path, clock, stub=stub)
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        light = hub.world.native["mqtt:light_01"]
        cooktop = hub.world.native["mqtt:cooktop_01"]
        assert light.values["color"]["hue"] == 330 and cooktop.values["child_lock"] is True

        clock.advance(minutes=1)
        await hub.cycle()
        assert light.values["color"]["hue"] == 330 and cooktop.values["child_lock"] is False
        assert [row["items"] for row in stub.executions if row["kind"] == "restore"] == [
            [{"device": "light_01", "status": "withheld_end_not_observed"}],
            [{"device": "cooktop_01", "status": "restored"}],
        ]
        await hub.shutdown()
        hub.boot()
        await hub.reconcile()
        clock.advance(seconds=1)
        hub.world.signal("presence.room_empty", "mqtt:sim_presence")
        await hub.cycle()
        assert len(hub.world.commands) == 3

        stub.paused = True
        stub.advance(ordinary, cancelled=[{"task_id": protected["task_id"], "restore": True}])
        await hub.reconcile()
        await hub.cycle()
        assert light.values == {"color": {"kelvin": 3000}}
        assert len(hub.world.commands) == 4
        assert stub.executions[-1]["items"] == [{"device": "light_01", "status": "restored"}]
        await hub.close()
    run(exercise)


def test_example_installation_binds_display_off_to_play_mood():
    installation = Installation.load(INSTALLATION, "h_042")
    binding = installation.bindings["display_01"]
    assert binding.target == "mqtt:display_01"
    assert binding.desired(Action(device="display_01", cmd="off")) == {"play_mood": None}


@pytest.mark.parametrize("episode,clock_time,waiting", [
    ("ep_9150", "2026-11-04T19:42:00+09:00", {"t_fridge#1", "t_fridge#2"}),
    ("ep_9120", "2026-11-02T20:12:00+09:00", {"t_fridge#3"}),
])
def test_hub_at19_fixture_runtime_replays_remaining_episodes(tmp_path, episode, clock_time, waiting):
    async def exercise():
        clock = Clock(clock_time)
        hub = Scenario(tmp_path, clock, episode=episode)
        if episode == "ep_9150":
            install_birthday(hub)
        else:
            devices = fixture("devices.json", episode)["devices"]
            commands = {
                "cleaner_01": {"clean": "clean"},
                "speaker_01": {"play": "mix", "stop": {"fixed": {"mix": None}}},
                "oven_01": {"set_cook_standby": "preset"},
                "fridge_01": {"show_notice": "show_notice"},
            }
            hub.write(devices, {name: {"target": f"mqtt:{name}", "commands": mapping}
                                for name, mapping in commands.items()})
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        assert {row["task_id"] for row in (await hub.state())["waiting"]} == waiting
        assert hub.world.commands == []
        if episode == "ep_9120":
            clock.advance(days=1)
            calendar = await hub.http.put("/v1/households/h_051/calendar", json=fixture("calendar.json", episode))
            assert calendar.status_code == 202
            await hub.reconcile()
            assert {row["task_id"] for row in (await hub.state())["waiting"]} == {
                "t_fridge#3", "t_clean#1", "t_music#2",
            }
        await hub.close()
    run(exercise)


def test_fixture_pause_cancels_waiting_and_preserves_started_lifecycle(tmp_path):
    async def exercise():
        clock = Clock()
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        guest(hub.world, clock)
        await hub.cycle()
        light = deepcopy(hub.world.native["mqtt:light_01"].values)
        pause = await hub.http.post("/v1/households/h_042/pause", json={"paused": True})
        assert pause.status_code == 200
        await hub.reconcile()
        clock.advance(minutes=30)
        await hub.cycle()
        assert hub.world.native["mqtt:oven_01"].values["preset"] is None
        assert hub.world.native["mqtt:light_01"].values == light
        assert not (await hub.state())["waiting"]
        hub.world.signal("presence.room_empty", "mqtt:sim_presence")
        await hub.cycle()
        assert hub.world.native["mqtt:light_01"].values == {"color": {"kelvin": 3000}}
        resume = await hub.http.post("/v1/households/h_042/pause", json={"paused": False})
        assert resume.status_code == 200
        await hub.reconcile()
        await hub.cycle()
        assert hub.world.native["mqtt:oven_01"].values["preset"] is None
        await hub.close()
    run(exercise)


def test_reconnect_restores_only_after_fresh_observation(tmp_path):
    async def exercise():
        clock = Clock()
        stub = Stub(clock, task(clock))
        hub = Scenario(tmp_path, clock, stub=stub)
        install_light(hub)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        clock.advance(minutes=1)
        hub.world.signal("event_end", "home")
        hub.mqtt.gap()
        hub.mqtt.online = False
        await hub.cycle()
        assert len(hub.world.commands) == 1
        assert stub.executions[-1]["items"] == [{"device": "light_01", "status": "unknown"}]
        hub.mqtt.online = True
        await hub.cycle()
        assert len(hub.world.commands) == 2
        assert hub.world.native["light"].values == {"color": {"kelvin": 3000}}
        assert stub.executions[-1]["items"] == [{"device": "light_01", "status": "restored"}]
        await hub.close()
    run(exercise)


def test_hub_at12_replacement_cancellation_leaves_other_plan_and_item_waiting(tmp_path):
    async def exercise():
        clock = Clock()
        started = task(clock)
        same_card = task(clock, n=2, trigger={"event": "guest_arrived"})
        notice = task(clock, n=3, trigger={"event": "package.brought_in", "released": False})
        notice["source"] = "item"
        other_card = task(clock, n=4, trigger={"event": "guest_arrived"})
        stub = Stub(clock, started, same_card, notice, other_card)
        hub = Scenario(tmp_path, clock, stub=stub)
        first, first_binding, first_native = light_config()
        second, second_binding, second_native = light_config(target="other", logical="light_02")
        other_card["actions"] = [action("light_02")]
        hub.write([first, second], {"light_01": first_binding, "light_02": second_binding})
        hub.world.add(*first_native)
        hub.world.add(*second_native)
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        stub.advance(notice, other_card, cancelled=[
            {"task_id": started["task_id"], "restore": True},
            {"task_id": same_card["task_id"], "restore": False},
        ])
        await hub.reconcile()
        assert {row["task_id"] for row in (await hub.state())["waiting"]} == {"t_test#3", "t_test#4"}
        hub.world.signal("doorbell.rang", "doorbell")
        hub.world.signal("door_lock.unlocked", "lock")
        await hub.cycle()
        assert [entry["target"] for entry in hub.world.commands] == ["light", "light", "other"]
        assert hub.world.native["light"].values["color"] == {"kelvin": 3000}
        assert {row["task_id"] for row in (await hub.state())["waiting"]} == {"t_test#3"}
        await hub.close()
    run(exercise)


def test_partial_restore_writes_only_owned_properties_and_uses_revision_witnesses(tmp_path):
    async def exercise():
        clock = Clock()
        stub = Stub(clock, task(clock))
        hub = Scenario(tmp_path, clock, stub=stub)
        device, binding, _ = light_config()
        binding["commands"] = {"color": {"properties": {
            "hue": "hue", "saturation": "saturation", "brightness": "brightness",
        }}}
        hub.write([device], {"light_01": binding})
        hub.world.add("light", "light", {"hue": 0, "saturation": 0, "brightness": 50}, ["color"])
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        clock.advance(seconds=1)
        hub.world.change("light", {"hue": 85})
        clock.advance(seconds=1)
        hub.world.signal("event_end", "home")
        await hub.cycle()
        restore = hub.world.commands[-1]
        assert restore["desired"] == {"saturation": 0, "brightness": 50}
        assert restore["expected"].keys() == restore["desired"].keys()
        assert hub.world.native["light"].values == {"hue": 85, "saturation": 0, "brightness": 50}
        assert stub.executions[-1]["items"] == [{"device": "light_01", "status": "skipped_user_changed"}]
        await hub.close()
    run(exercise)
