import asyncio
import json
from copy import deepcopy
from datetime import datetime, timedelta
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
        assert [row["by"] for row in state["ledger"]
                if row.get("device") == "light_02" and row["kind"] == "event"] == ["unknown", "unknown"]
        kept = next(row for row in state["ledger"] if row["kind"] == "restore" and row["device"] == "light_02")
        assert kept["what"] == "바뀐 기기 상태 유지" and kept["by"] == "hub"
        page = (await hub.dashboard.get("/")).text
        ledger, detail = page.split('<section id="detail"', 1)
        assert "TV · 파티 화면 · 실행 확인 안 됨" in ledger
        assert ledger.count('class="pill actor">기기 보고</span>') == 2
        assert "바뀐 기기 상태 유지" in ledger
        order = [detail.index(title) for title in ("Waiting work", "Command acknowledgement and read-back",
                 "Person actions and C-3 events", "Restoration and skips")]
        assert order == sorted(order)
        assert all(label in detail for label in ("Class A assumption", "virtual", "physical", "ACCEPTED",
                   "unverifiable", "skipped_user_changed", "restored", "Received by Server", "C-3 payload"))
        assert "ground_truth_actor" not in page
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
        pending = (await hub.state())["ledger"][-1]["reports"]
        assert [report["kind"] for report in pending] == ["run", "event"]
        assert all(not report["delivered"] and report["delivery_error"] == "HTTP 503" for report in pending)
        page = (await hub.dashboard.get("/")).text
        ledger, detail = page.split('<section id="detail"', 1)
        assert "보내는 중" in ledger and "HTTP 503" not in ledger
        assert "HTTP 503" in detail

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
        state = await hub.state()
        assert state["commands"][0]["acknowledgement"] is None
        summary, = state["plan_summaries"]
        assert summary["triggered"] == 2
        assert summary["completed"] == 1
        assert summary["failed_unknown_unverifiable"] == 1
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
        page = (await hub.dashboard.get("/")).text
        ledger, detail = page.split('<section id="detail"', 1)
        assert release_status in detail
        assert "되돌림 확인" in ledger
        assert ("일정이 끝난 뒤 되돌림 확인" in ledger) == observed_end
        assert ("끝났는지 확인되지 않아 그대로 유지" in ledger) == (not observed_end)
        state = (await hub.dashboard.get("/state")).json()
        summary, = state["plan_summaries"]
        assert summary["restored"] == (2 if observed_end else 1)
        assert summary["withheld"] == (0 if observed_end else 1)
        safety = next(row["steps"] for row in state["task_stories"] if row["task_id"] == "t_safe#2")
        end = next(step for step in safety if step["kind"] == "end")
        assert end["how"] == ("event" if observed_end else "fallback")
        assert {item["status"] for item in safety[-1]["items"]} == {release_status}
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
            state = (await hub.dashboard.get("/state")).json()
            v1, v2 = state["plan_history"]
            assert v1["changes"]["added"] == ["t_fridge#3"]
            assert v2["previous_version"] == 1
            assert v2["changes"]["added"] == ["t_clean#1", "t_music#2"]
            cleaning = next(row["steps"] for row in state["task_stories"] if row["task_id"] == "t_clean#1")
            assert cleaning == [
                {"kind": "admitted", "at": clock().isoformat(), "plan_version": 2},
                {"kind": "waiting", "at": clock().isoformat(), "plan_version": 2,
                 "trigger": {"time": "2026-11-07T16:30:00+09:00"}},
            ]
        else:
            state = (await hub.dashboard.get("/state")).json()
            assert state["plan_summaries"] == [{
                "plan_id": "ep_9150", "plan_version": 1, "current": True,
                "device_actions": 0, "notices": 2, "waiting": 2, "window_passed": 0,
                "triggered": 0, "completed": 0, "failed_unknown_unverifiable": 0,
                "restored": 0, "withheld": 0,
            }]
            assert "device actions 0" in (await hub.dashboard.get("/")).text
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


@pytest.mark.parametrize("matched", [False, True])
def test_dashboard_reports_missed_window_without_changing_eligibility(tmp_path, matched):
    async def exercise():
        clock = Clock("2026-10-17T13:40:00+09:00")
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        if matched:
            guest(hub.world, clock)
        clock.now = clock.now.replace(hour=17, minute=0, second=0)
        state = (await hub.dashboard.get("/state")).json()
        mood = next(row for row in state["waiting"] if row["task_id"] == "t_mood#3")
        assert mood["status"] == "waiting"
        clock.advance(seconds=1)
        state = (await hub.dashboard.get("/state")).json()
        assert state == await hub.state()
        mood = next(row for row in state["waiting"] if row["task_id"] == "t_mood#3")
        assert state["plan_summaries"][0]["window_passed"] == (0 if matched else 1)
        if matched:
            assert mood["status"] == "waiting"
        else:
            assert mood["status"] == "window_passed"
            assert mood["window_passed_at"] == "2026-10-17T17:00:00+09:00"
            assert mood["trigger"]["event"] == "guest_arrived"
            assert "Window passed · 2026-10-17T17:00:00+09:00" in (await hub.dashboard.get("/")).text
            guest(hub.world, clock)
        await hub.cycle()
        assert any(row["target"] == "mqtt:light_01" for row in hub.world.commands) == matched
        if not matched:
            clock.advance(hours=4)
            await hub.cycle()
            mood = next(row for row in (await hub.state())["waiting"] if row["task_id"] == "t_mood#3")
            assert mood["status"] == "window_passed"
        await hub.close()
    run(exercise)


def test_dashboard_records_release_cancellation_and_removal_across_restart(tmp_path):
    async def exercise():
        clock = Clock("2026-10-16T18:04:00+09:00")
        v1 = fixture("plan.v1.json")
        v3 = fixture("plan.v3.json")
        fridge = next(task for task in v1["tasks"] if task["task_id"] == "t_fridge#5")
        released = next(task for task in v3["tasks"] if task["task_id"] == fridge["task_id"])
        cleaning, safety = v1["tasks"][:2]
        stub = Stub(clock, fridge, cleaning, safety)
        hub = Scenario(tmp_path, clock, stub=stub)
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        received = clock.advance(minutes=2)
        stub.advance(released, cancelled=[{"task_id": cleaning["task_id"], "restore": False}])
        assert await hub.runtime.refresh()
        state = (await hub.dashboard.get("/state")).json()
        initial, updated = state["plan_history"]
        assert initial["ack"]["delivered"] is True
        assert updated == {
            "plan_id": "ep_test", "plan_version": 2, "previous_version": 1, "received_at": received,
            "ack": {"delivered": False, "delivery_error": None, "packet": {
                "plan_version": 2, "status": "admitted", "rejected_tasks": [],
            }},
            "changes": {
                "added": [], "removed": ["t_clean#1", "t_safe#2"],
                "cancelled": [{"task_id": "t_clean#1", "restore": False}],
                "triggers_changed": [{"task_id": fridge["task_id"],
                                      "from": fridge["trigger"], "to": released["trigger"]}],
            },
        }
        await hub.shutdown()
        hub.boot()
        await hub.reconcile()
        await hub.cycle()
        state = (await hub.dashboard.get("/state")).json()
        assert [row["plan_version"] for row in state["plan_history"]] == [1, 2]
        assert state["plan_history"][1]["ack"]["delivered"] is True
        assert state["plan_history"][1]["changes"] == updated["changes"]
        notice = next(row["steps"] for row in state["task_stories"] if row["task_id"] == fridge["task_id"])
        assert [step["kind"] for step in notice] == [
            "admitted", "waiting", "admitted", "waiting", "triggered", "command",
        ]
        assert notice[-2]["how"] == "server_release"
        assert notice[-2]["at"] == released["trigger"]["at"]
        assert notice[-1]["status"] == "completed"
        page = (await hub.dashboard.get("/")).text
        assert "Plan history" in page and "triggers_changed" in page
        await hub.close()
    run(exercise)


def test_dashboard_orders_birthday_mood_story(tmp_path):
    async def exercise():
        clock = Clock("2026-10-17T13:40:00+09:00")
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()
        guest(hub.world, clock)
        await hub.cycle()
        clock.advance(minutes=10)
        hub.world.change("mqtt:light_01", {"color": {"kelvin": 2700}}, local=True)
        clock.advance(minutes=30)
        hub.world.signal("presence.room_empty", "mqtt:sim_presence")
        await hub.cycle()
        clock.advance(minutes=1)
        hub.world.change("mqtt:light_01", {"color": {"kelvin": 2900}}, local=True)
        await hub.cycle()
        await hub.shutdown()
        hub.boot()
        await hub.reconcile()
        state = (await hub.dashboard.get("/state")).json()
        mood = next(row["steps"] for row in state["task_stories"] if row["task_id"] == "t_mood#3")
        assert [step["kind"] for step in mood] == [
            "admitted", "waiting", "triggered", "command", "command",
            "person_change", "end", "command", "restore_result",
        ]
        admitted, waiting, triggered, display, light, person, end, restore, result = mood
        assert admitted["plan_version"] == 1
        assert waiting["trigger"]["event"] == "guest_arrived"
        events = {row["packet"][0]["event_id"]: row["packet"][0] for row in state["events"]}
        assert triggered["at"] == events[triggered["event_id"]]["at"]
        assert triggered["event_type"] == "guest_arrived"
        assert (display["device"], light["device"]) == ("display_01", "light_01")
        for command in (display, light, restore):
            assert command["acknowledgement"]["status"] == "ACCEPTED"
            assert {prop: command["read_back"]["values"][prop] for prop in command["desired"]} == command["desired"]
        assert (display["status"], light["status"], restore["status"]) == ("completed", "completed", "restored")
        assert person["by"] == "user"
        assert person["payload"]["to"] == {"kelvin": 2700}
        assert person["device"] == "light_01"
        assert end["how"] == "event" and events[end["event_id"]]["type"] == "event_end"
        assert restore["phase"] == "restore" and restore["desired"] == {"play_mood": None}
        assert {item["device"]: item["status"] for item in result["items"]} == {
            "display_01": "restored", "light_01": "skipped_user_changed",
        }
        page = (await hub.dashboard.get("/")).text
        assert "Task stories" in page and "Person change" in page
        await hub.close()
    run(exercise)


def test_hub_at20_birthday_seen_ledger(tmp_path):
    async def exercise():
        clock = Clock("2026-10-15T21:11:55+09:00")
        hub = Scenario(tmp_path, clock, episode="ep_9031")
        install_birthday(hub)
        hub.world.native["mqtt:fridge_01"].spec.update(
            local_operation_reporting=True, assumption="Virtual panel assumed",
        )
        hub.boot()
        await hub.runtime.discover()
        assert await hub.runtime.refresh()
        pending, = (await hub.state())["ledger"]
        assert pending["reports"] == [
            {"kind": "ack", "id": "ep_9031/1", "delivered": False, "delivery_error": None},
        ]
        page = (await hub.dashboard.get("/")).text
        ledger_page, _ = page.split('<section id="detail"', 1)
        assert '<time datetime="2026-10-15T21:11:55+09:00" title="2026-10-15 21:11:55 KST">21:11</time>' in ledger_page
        assert "보내는 중" in ledger_page and "서버에 보냄" not in ledger_page
        await hub.runtime.flush()

        def at(instant):
            clock.now = datetime.fromisoformat(instant)

        at("2026-10-16T08:40:00+09:00")
        response = await hub.http.post("/v1/cards/nc_331/reactions", json=fixture("reactions.json")[0])
        assert response.status_code == 200
        await hub.reconcile()
        at("2026-10-16T18:05:10+09:00")
        hub.world.signal("camera.package_removed", "mqtt:sim_camera", removed_count=1, remaining_count=0)
        await hub.runtime.flush()
        await hub.cycle()
        at("2026-10-16T18:07:44+09:00")
        hub.world.change("mqtt:fridge_01", {}, event="fridge.door_opened", local=True)
        await hub.cycle()
        at("2026-10-17T13:30:00+09:00")
        await hub.cycle()
        at("2026-10-17T13:52:29+09:00")
        guest(hub.world, clock)
        await hub.cycle()
        at("2026-10-17T14:00:00+09:00")
        await hub.cycle()
        at("2026-10-17T14:20:02+09:00")
        hub.world.change("mqtt:oven_01", {"in_use": True}, event="oven.started", local=True, job="job_person")
        at("2026-10-17T15:10:05+09:00")
        hub.world.change("mqtt:light_01", {"color": {"kelvin": 2700}}, local=True)
        await hub.cycle()
        at("2026-10-17T17:50:00+09:00")
        hub.world.signal("presence.room_empty", "mqtt:sim_presence")
        await hub.runtime.step()
        pending = (await hub.state())["ledger"][-5:]
        assert [row["reports"][0]["kind"] for row in pending] == ["event", "restore", "restore", "restore", "restore"]
        assert all(not report["delivered"] for row in pending for report in row["reports"])
        await hub.runtime.flush()
        await hub.shutdown()
        hub.boot()
        await hub.reconcile()

        response = await hub.dashboard.get("/state")
        assert response.status_code == 200
        state = response.json()
        assert state["household"] == "h_042"
        assert state["current_plans"] == [{"plan_id": "ep_9031", "plan_version": 3, "task_count": 5}]
        assert state["server_confirmed"]
        ledger = state["ledger"]
        assert [row["at"] for row in ledger] == sorted(row["at"] for row in ledger)
        assert [(row["label"], row["what"], row["by"], [item["kind"] for item in row["reports"]])
                for row in ledger] == [
            ("—", "계획 v1 받음 · 할 일 6", "hub", ["ack"]),
            ("—", "계획 v2 받음 · 할 일 5 · 청소기 취소", "hub", ["ack"]),
            ("현관", "택배 들임", "hub", ["event"]),
            ("—", "계획 v3 받음 · 할 일 5 · 택배 기다림 끝", "hub", ["ack"]),
            ("냉장고", "안내 표시", "spira", ["run", "event"]),
            ("냉장고", "안내 표시", "spira", ["run", "event"]),
            ("냉장고", "문 열림", "user", ["event"]),
            ("인덕션", "잠금", "spira", ["run", "event"]),
            ("전기포트", "끔", "spira", ["run", "event"]),
            ("현관", "손님 도착", "hub", ["event"]),
            ("TV", "어린이 파티 화면", "spira", ["run", "event"]),
            ("조명", "색조 330°", "spira", ["run", "event"]),
            ("오븐", "170° 20분 대기", "spira", ["run", "event"]),
            ("오븐", "시작", "user", ["event"]),
            ("조명", "색조 330° → 2700K", "user", ["event"]),
            ("—", "일정이 끝난 것을 확인", "hub", ["event"]),
            ("인덕션", "일정이 끝난 뒤 되돌림 확인 · 잠금 해제", "spira", ["restore", "event"]),
            ("전기포트", "일정이 끝난 뒤 되돌림 확인 · 켜짐", "spira", ["restore", "event"]),
            ("TV", "일정이 끝난 뒤 되돌림 확인 · 꺼짐", "spira", ["restore", "event"]),
            ("조명", "사람이 바꾼 설정 유지", "hub", ["restore"]),
        ]
        assert ledger[12]["acknowledgement"]["status"] == "ACCEPTED"
        assert ledger[12]["read_back"]["preset"] == {"temp_c": 170, "minutes": 20}
        assert ledger[-1]["status"] == "skipped_user_changed"
        reports = [report for row in ledger for report in row["reports"]]
        assert all(report["delivered"] and report["delivery_error"] is None for report in reports)
        receipts = await hub.receipts()
        events = {event["event_id"]: event for batch in receipts["events"] for event in batch}
        assert [events[row["reports"][0]["id"]]["payload"]["by"] for row in ledger[13:15]] == ["user", "user"]
        assert {report["id"] for report in reports if report["kind"] == "event"} == events.keys()
        assert {report["id"] for report in reports if report["kind"] in {"run", "restore"}} == {
            item["result_id"] for item in receipts["executions"]
        }

        page = (await hub.dashboard.get("/")).text
        ledger_page, detail = page.split('<section id="detail"', 1)
        assert "Hub · 이 집이 본 것" in ledger_page
        assert "h_042 · 계획 v3 · 할 일 5 · 서버 연결됨" in ledger_page
        assert 'href="#detail">자세한 기록</a>' in ledger_page
        assert 'href="/state"' in detail and "Waiting work" in detail
        assert ledger_page.count('<li class="ledger-row">') == len(ledger)
        assert ledger_page.count("서버에 보냄") == len(ledger)
        assert all(label not in ledger_page for label in ("ack 204", "event 보냄", "restore 보냄", "ep_9031"))
        rows = ledger_page.split('<li class="ledger-row">')[1:]
        for markup, row in zip(rows, reversed(ledger), strict=True):
            assert f'datetime="{row["at"]}"' in markup and row["what"] in markup
        assert "<span>10/17</span> 17:50" in rows[0] and "<span>10/15</span> 21:11" in rows[-1]
        assert 'class="pill actor">사람</span>' in ledger_page
        assert 'class="pill actor">집</span>' in ledger_page
        assert 'class="pill actor">SPIRA</span>' in ledger_page
        for asset in ("dashboard.css", "dashboard.js"):
            assert f'"/assets/{asset}"' in page
            assert (await hub.dashboard.get(f"/assets/{asset}")).status_code == 200
        await hub.close()
    run(exercise)


def test_dashboard_keeps_prior_ack_after_database_upgrade(tmp_path):
    async def exercise():
        clock = Clock()
        original = task(clock, trigger={"time": (clock() + timedelta(minutes=5)).isoformat()})
        stub = Stub(clock, original)
        hub = Scenario(tmp_path, clock, stub=stub)
        install_light(hub)
        hub.boot()
        await hub.reconcile()
        # Before the dashboard recorded versions, the Hub kept only current tasks and ack packets.
        with hub.store.db:
            hub.store.db.execute("DROP TABLE plan_versions")
        await hub.shutdown()
        hub.boot()
        await hub.reconcile()
        prior, = (await hub.state())["plan_history"]
        assert prior["ack"]["delivered"] is True and prior["changes"] is None
        assert prior["plan_version"] == 1
        clock.advance(minutes=1)
        changed = task(clock, trigger={"time": (clock() + timedelta(minutes=10)).isoformat()})
        stub.advance(changed)
        await hub.reconcile()
        earlier, latest = (await hub.state())["plan_history"]
        assert earlier == prior
        assert latest["previous_version"] == 1
        assert latest["changes"]["triggers_changed"] == [
            {"task_id": original["task_id"], "from": original["trigger"], "to": changed["trigger"]},
        ]
        await hub.close()
    run(exercise)
