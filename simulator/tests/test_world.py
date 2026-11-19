import json
import sqlite3
from datetime import datetime

import pytest
from conftest import CLEANER, LIGHT, OVEN, PLUG, Wire, fixture_json
from fastapi.testclient import TestClient
from spira_contracts.devices import Devices
from spira_contracts.plan import Plan
from spira_simulator.api import create_app
from spira_simulator.profile import DEFAULT_PROFILE, load_profile
from spira_simulator.storage import UnsupportedSchema
from spira_simulator.world import World


def test_sim_at01_configured_household_without_peers(wire, tmp_path):
    discovery, signals = wire.request("discover")
    fixture = Devices.model_validate(fixture_json("ep_9031/devices.json"))
    configured = load_profile()
    logical = {d.target: d.logical_id for d in configured.devices}
    expected = {d.id: d for d in fixture.devices}
    assert {logical[d["target"]] for d in discovery["devices"]} == set(expected)
    assert not signals
    for device in discovery["devices"]:
        source = expected[logical[device["target"]]]
        assert device["device_type"] == source.type
        assert device["capabilities"]["commands"] == [
            command.cmd for command in source.commands
        ]
        assert device["available"]
        assert wire.read(device["target"])["values"].keys() == set(
            device["capabilities"]["properties"]
        )
    with TestClient(create_app(tmp_path / "web.db", broker_enabled=False)) as client:
        assert client.get("/sim/viewer").status_code == 200
        snapshot = client.get("/sim/snapshot").json()
        assert snapshot["household_id"] == fixture.household_id
        assert {logical[d["target"]] for d in snapshot["devices"]} == set(expected)
        assert all(d["observation"] == "current" for d in snapshot["devices"])


def test_family_gathering_profile_and_speaker_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("WORLD_PROFILE", str(DEFAULT_PROFILE.with_name("ep_9120.json")))
    fixture = Devices.model_validate(fixture_json("ep_9120/devices.json"))
    plan = Plan.model_validate(fixture_json("ep_9120/plan.v2.json"))
    expected = {f"mqtt:{device.id}": device for device in fixture.devices}
    speaker = "mqtt:speaker_01"

    app = create_app(tmp_path / "family.db", broker_enabled=False)
    with TestClient(app) as client:
        world = app.state.world
        wire = Wire(world)
        assert client.get("/sim/snapshot").json()["household_id"] == fixture.household_id
        discovered, _ = wire.request("discover")
        assert {device["target"] for device in discovered["devices"]} == set(expected)
        for device in discovered["devices"]:
            source = expected[device["target"]]
            assert device["device_type"] == source.type
            assert device["capabilities"]["commands"] == [
                command.cmd for command in source.commands
            ]
        assert world.profile.home_signals == load_profile().home_signals
        for action, facts in load_profile().home_signals.items():
            assert [
                (s["target"], s["event_type"], s["payload"])
                for s in world.home_event(action)
            ] == [(f.target, f.event_type, f.payload) for f in facts]

        play = next(
            action
            for task in plan.tasks
            for action in task.actions
            if action.device == expected[speaker].id
        )
        before = wire.read(speaker)
        receipt, (changed,) = wire.command(speaker, {"play": play.value})
        assert receipt["status"] == "ACCEPTED" and receipt["job_id"] is None
        assert changed["event_type"] == "speaker.changed"
        assert changed["operation_id"] == receipt["operation_id"]
        playing = wire.read(speaker)
        assert playing["values"] == {"play": play.value}
        assert playing["revisions"]["play"] != before["revisions"]["play"]

        for invalid in (
            {"playlist": "birthday", "volume": 25},
            {"playlist": "family", "volume": 101},
            {"playlist": "family", "volume": -1},
            {"playlist": "family"},
            {"volume": 25},
        ):
            receipt, signals = wire.command(speaker, {"play": invalid})
            assert receipt["status"] == "REJECTED" and not signals
            assert wire.read(speaker)["revisions"] == playing["revisions"]

        receipt, _ = wire.command(speaker, {"play": None}, expected=before["revisions"])
        assert receipt["status"] == "CONFLICT"
        receipt, (stopped,) = wire.command(
            speaker, {"play": None}, expected=playing["revisions"]
        )
        assert receipt["status"] == "ACCEPTED"
        assert stopped["event_type"] == "speaker.changed"
        assert wire.read(speaker)["values"] == before["values"] == {"play": None}


@pytest.mark.parametrize("episode", ["ep_9031", "ep_9120"])
def test_demo_profiles_label_every_command_basis(episode):
    profile = load_profile(DEFAULT_PROFILE.with_name(f"{episode}.json"))
    for device in profile.devices:
        assert set(device.command_basis) == set(device.commands)
        assert set(device.command_basis.values()) <= {"sdk", "lg_assumed", "standard"}


@pytest.mark.parametrize(
    "episode, device_id, prop, value, invalid",
    [
        ("ep_9031", "air_purifier_01", "mode", "AUTO", "INVALID"),
        ("ep_9031", "air_purifier_01", "wind_strength", "HIGH", "INVALID"),
        ("ep_9120", "air_purifier_01", "wind_strength", "HIGH", "INVALID"),
        ("ep_9031", "dishwasher_01", "course", "NORMAL", "INVALID"),
        ("ep_9031", "dishwasher_01", "delay_hours", 12, 13),
        ("ep_9031", "washer_01", "course", "NORMAL", "INVALID"),
        ("ep_9031", "plug_iron", "power", False, "off"),
    ],
)
def test_added_devices_report_command_effect_and_readback(
    tmp_path, clock, episode, device_id, prop, value, invalid
):
    profile = load_profile(DEFAULT_PROFILE.with_name(f"{episode}.json"))
    fixture = Devices.model_validate(fixture_json(f"{episode}/devices.json"))
    device = next(device for device in fixture.devices if device.id == device_id)
    target = f"mqtt:{device_id}"
    world = World(tmp_path / "expanded.db", profile, clock)
    try:
        wire = Wire(world)
        if device_id == "plug_iron":
            world.local_change(target, "resident", {"power": True})
        before = wire.read(target)
        desired = {prop: value}
        receipt, (changed,) = wire.command(
            target, desired, expected={prop: before["revisions"][prop]}
        )
        assert receipt["status"] == "ACCEPTED"
        assert receipt["job_id"] is None
        assert changed["event_type"] == f"{device.type}.changed"
        assert "changed" in device.events
        assert changed["operation_id"] == receipt["operation_id"]
        after = wire.read(target)
        assert after["values"] == changed["values"] == {**before["values"], **desired}
        assert after["revisions"] == changed["revisions"]
        assert after["revisions"][prop] != before["revisions"][prop]

        receipt, signals = wire.command(target, {prop: invalid})
        assert receipt["status"] == "REJECTED" and not signals
        if "start" in device.never:
            receipt, signals = wire.command(target, {"start": True})
            assert receipt["status"] == "PROHIBITED" and not signals
        assert wire.read(target)["revisions"] == after["revisions"]

        receipt, _ = wire.command(
            target, {prop: before["values"][prop]}, expected=after["revisions"]
        )
        assert receipt["status"] == "ACCEPTED"
        assert wire.read(target)["values"] == before["values"]
    finally:
        world.store.close()


def test_router_plug_refuses_hub_off_but_supports_household_control(wire, world):
    target = "mqtt:plug_router"
    discovery, _ = wire.request("discover")
    router = next(device for device in discovery["devices"] if device["target"] == target)
    assert router["capabilities"]["commands"] == []
    before = wire.read(target)
    receipt, signals = wire.command(target, {"power": False})
    assert receipt["status"] == "PROHIBITED" and not signals
    assert wire.read(target)["values"] == before["values"] == {"power": True}
    assert wire.read(target)["revisions"] == before["revisions"]

    (changed,) = world.local_change(target, "resident", {"power": False})
    assert changed["event_type"] == "smart_plug.changed"
    assert changed["local_operation"] is False
    assert wire.read(target)["values"] == {"power": False}


def test_sim_at03_local_change_survives_restart_and_remains_private(tmp_path, clock):
    path = tmp_path / "world.db"
    world = World(path, load_profile(), clock)
    wire = Wire(world)
    before = wire.read(LIGHT)
    world.local_change(LIGHT, "resident", {"color": {"kelvin": 2700}})
    after = wire.read(LIGHT)
    assert after["values"]["color"] == {"kelvin": 2700}
    assert before["revisions"]["color"] != after["revisions"]["color"]
    snapshot = world.snapshot()
    prior_truth = world.store.truth()
    world.store.close()
    restarted = World(path, load_profile(), clock)
    try:
        assert restarted.snapshot() == snapshot
        readback = Wire(restarted).read(LIGHT)
        assert (
            readback["values"] == after["values"]
            and readback["revisions"] == after["revisions"]
        )
        assert restarted.store.truth() == prior_truth
        assert prior_truth[0]["actor"] == "resident"
    finally:
        restarted.store.close()


def test_sim_at04_duplicate_acknowledgement_after_restart(tmp_path, clock):
    path = tmp_path / "world.db"
    world = World(path, load_profile(), clock)
    wire = Wire(world)
    acknowledgement, signals = wire.command(
        LIGHT, {"color": {"kelvin": 2700}}, "op_original"
    )
    assert acknowledgement == {
        "status": "ACCEPTED",
        "operation_id": "op_original",
        "job_id": None,
    }
    assert len(signals) == 1 and signals[0]["operation_id"] == "op_original"
    assert signals[0]["local_operation"] is False
    assert wire.command(LIGHT, {"color": {"kelvin": 2700}}, "op_original") == (
        acknowledgement,
        [],
    )
    changed = wire.read(LIGHT)
    world.store.close()

    restarted = World(path, load_profile(), clock)
    try:
        wire = Wire(restarted)
        # Even a different body under the same operation identity has the original receipt.
        assert wire.command(LIGHT, {"color": {"kelvin": 3000}}, "op_original") == (
            acknowledgement,
            [],
        )
        assert wire.read(LIGHT)["revisions"] == changed["revisions"]
        assert len(restarted.store.truth()) == 1
    finally:
        restarted.store.close()


def test_sim_at05_accepted_unchanged_and_explicit_rejection(world, wire):
    before = wire.read(LIGHT)
    desired = {"color": {"kelvin": 2700}}
    world.set_fault(LIGHT, "command", "unchanged")
    acknowledgement, signals = wire.command(LIGHT, desired)
    assert acknowledgement["status"] == "ACCEPTED" and not signals
    assert wire.read(LIGHT)["values"] == before["values"]
    assert wire.read(LIGHT)["revisions"] == before["revisions"]
    world.set_fault(LIGHT, "command", "reject")
    acknowledgement, signals = wire.command(LIGHT, desired)
    assert acknowledgement["status"] == "REJECTED" and not signals
    assert world.store.truth() == []


def test_sim_at06_restore_conflicts_after_independent_away_and_back(world, wire):
    before = wire.read(LIGHT)
    wire.command(LIGHT, {"color": {"kelvin": 3200}})
    prepared = wire.read(LIGHT)
    world.local_change(LIGHT, "external_automation", {"color": {"kelvin": 2700}})
    (pushed,) = world.local_change(
        LIGHT, "external_automation", {"color": {"kelvin": 3200}}
    )
    (equal,) = world.local_change(LIGHT, "resident", {"color": {"kelvin": 3200}})
    assert equal["revisions"]["color"] != pushed["revisions"]["color"]
    assert pushed["operation_id"] is None and not pushed["local_operation"]
    receipt, signals = wire.command(
        LIGHT,
        {"color": before["values"]["color"]},
        expected={"color": prepared["revisions"]["color"]},
    )
    assert receipt["status"] == "CONFLICT" and not signals
    assert wire.read(LIGHT)["values"]["color"] == {"kelvin": 3200}


def test_sim_at07_running_job_is_durable_and_completion_is_device_self(tmp_path, clock):
    path = tmp_path / "world.db"
    world = World(path, load_profile(), clock)
    wire = Wire(world)
    receipt, changes = wire.command(CLEANER, {"clean": {"room": "거실"}})
    assert receipt["status"] == "ACCEPTED"
    (start,) = changes
    assert start["job_id"] == receipt["job_id"]
    assert start["values"]["job_status"] == "running"
    assert start["operation_id"] == receipt["operation_id"]
    running = wire.read(CLEANER)
    world.store.close()

    restarted = World(path, load_profile(), clock)
    try:
        wire = Wire(restarted)
        assert wire.read(CLEANER)["job_id"] == receipt["job_id"]
        assert wire.read(CLEANER)["revisions"] == running["revisions"]
        clock.advance(30)
        (completed,) = restarted.complete_due()
        assert completed["job_id"] == receipt["job_id"] == wire.read(CLEANER)["job_id"]
        assert completed["values"]["job_status"] == "completed"
        assert completed["event_type"] == "cleaner.completed"
        assert completed["operation_id"] is None and not completed["local_operation"]
        assert restarted.complete_due() == []
    finally:
        restarted.store.close()


def test_sim_at08_stop_and_foreign_replacement_retire_old_job(world, wire, clock):
    original, _ = wire.command(CLEANER, {"clean": {"room": "거실"}})
    prior = wire.read(CLEANER)
    clock.advance(10)
    (outside,) = world.local_change(CLEANER, "resident", {"clean": {"room": "거실"}})
    assert outside["job_id"] != original["job_id"]
    for expected in ({}, {"clean": prior["revisions"]["clean"]}):
        receipt, _ = wire.command(CLEANER, {"clean": None}, expected=expected)
        assert receipt["status"] == "CONFLICT"
    clock.advance(20)
    assert world.complete_due() == []
    current = wire.read(CLEANER)
    assert current["job_id"] == outside["job_id"] and current["values"]["in_use"]
    receipt, changes = wire.command(
        CLEANER, {"clean": None}, expected={"clean": current["revisions"]["clean"]}
    )
    assert (
        receipt["status"] == "ACCEPTED"
        and changes[0]["values"]["job_status"] == "stopped"
    )
    clock.advance(30)
    assert world.complete_due() == []
    assert wire.read(CLEANER)["values"]["job_status"] == "stopped"


@pytest.mark.parametrize("mode", ["stale", "missing", "unavailable"])
def test_sim_at09_readback_fault_does_not_change_world(world, wire, clock, mode):
    before = wire.read(LIGHT)
    world.set_fault(LIGHT, "readback", mode)
    clock.advance()
    receipt, signals = wire.command(LIGHT, {"color": {"kelvin": 2700}})
    assert receipt["status"] == "ACCEPTED" and not signals
    report = wire.read(LIGHT)
    if mode == "stale":
        assert report["values"] == before["values"]
        assert datetime.fromisoformat(report["observed_at"]) < clock()
    else:
        assert report["available"] == (mode == "missing")
        assert report["values"] == {} and report["revisions"] == {}
    assert (
        next(d for d in world.snapshot()["devices"] if d["target"] == LIGHT)[
            "observation"
        ]
        == mode
    )
    world.set_fault(LIGHT, "readback", "current")
    assert wire.read(LIGHT)["values"]["color"] == {"kelvin": 2700}


def test_sim_at14_invalid_multi_property_write_cannot_change_values_or_witnesses(
    world, wire
):
    before = wire.read(LIGHT)
    for invalid, status in [
        ({"color": {"kelvin": 100}}, "REJECTED"),
        ({"missing_property": True}, "UNSUPPORTED"),
        ({"color": {"kelvin": 2700, "by": "user"}}, "REJECTED"),
    ]:
        receipt, signals = wire.command(LIGHT, {"power": False, **invalid})
        assert receipt["status"] == status and not signals
        assert wire.read(LIGHT)["revisions"] == before["revisions"]
        assert wire.read(LIGHT)["values"] == before["values"]
    assert world.store.truth() == []


def test_oven_local_start_survives_preset_restore_and_prohibits_remote_start(
    wire, world
):
    before = wire.read(OVEN)
    wire.command(OVEN, {"preset": {"temp_c": 170, "minutes": 20}})
    staged = wire.read(OVEN)
    assert not staged["values"]["in_use"]
    assert wire.command(OVEN, {"in_use": True})[0]["status"] == "PROHIBITED"
    (started,) = world.local_change(OVEN, "resident", {}, start=True)
    assert started["event_type"] == "oven.started" and started["local_operation"]
    assert started["operation_id"] is None
    wire.command(
        OVEN,
        {"preset": before["values"]["preset"]},
        expected={"preset": staged["revisions"]["preset"]},
    )
    live = wire.read(OVEN)
    assert live["values"]["in_use"] and live["job_id"] == started["job_id"]


def test_device_offline_is_unavailable_and_persistent(tmp_path, clock):
    path = tmp_path / "world.db"
    world = World(path, load_profile(), clock)
    (_,) = world.set_fault(PLUG, "link", "offline")
    wire = Wire(world)
    assert wire.command(PLUG, {"power": False})[0]["status"] == "UNAVAILABLE"
    world.store.close()
    restarted = World(path, load_profile(), clock)
    try:
        assert Wire(restarted).read(PLUG)["available"] is False
        restarted.set_fault(PLUG, "link", "online")
        assert Wire(restarted).read(PLUG)["values"]["power"] is True
    finally:
        restarted.store.close()


def test_v1_storage_preserves_light_state_witness_and_order(tmp_path, clock):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES('schema_version','1');
            CREATE TABLE control(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO control VALUES('world_revision','6');
            CREATE TABLE device_state(target TEXT PRIMARY KEY, body TEXT NOT NULL);
        """)
        db.execute(
            "INSERT INTO device_state VALUES('sim_light_01',?)",
            (
                json.dumps(
                    {
                        "values": {"power": False},
                        "revisions": {"power": "pr_before"},
                        "provenance": "user",
                        "observed_at": 1792213200.0,
                    }
                ),
            ),
        )
    world = World(path, load_profile(), clock)
    try:
        report = Wire(world).read(LIGHT)
        assert (
            not report["values"]["power"]
            and report["revisions"]["power"] == "pr_before"
        )
        assert report["world_revision"] == 6
        assert world.store.truth() == []
    finally:
        world.store.close()


def test_unsupported_future_schema_stays_intact(tmp_path, clock):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        db.execute("INSERT INTO schema_meta VALUES('schema_version','999')")
    before = path.read_bytes()
    with pytest.raises(UnsupportedSchema):
        World(path, load_profile(), clock)
    assert path.read_bytes() == before
