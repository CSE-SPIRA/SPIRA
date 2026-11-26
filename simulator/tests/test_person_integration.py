"""Exercise named person controls over the Simulator device protocol."""

import asyncio
import json
from xml.etree import ElementTree

import httpx2
import pytest
from conftest import CLEANER, LIGHT, Wire
from fastapi.testclient import TestClient
from spira_simulator.api import create_app
from spira_simulator.mqtt import DeviceProtocol
from spira_simulator.profile import DEFAULT_PROFILE, load_profile

from hub.tests.fixture_server import create_app as fixture_app
from hub.tests.fixture_server.test_fixture_server import HEADERS
from hub.tests.fixture_server.test_scene_support import (
    CARDS, CLOCK, PLANS, SELECT, finish_judgment, upload,
)
from hub.tests.runtime.peers import Clock, Scenario
from hub.tests.runtime.test_acceptance import install_birthday


def press(client, target, person, control):
    response = client.post(
        "/operator/person", params={"target": target},
        data={"person": person, "control": control}, follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.mark.provisional
def test_house_light_yellow_reaches_fixture_as_a_user_change(tmp_path, monkeypatch):
    shell_origin = "http://127.0.0.1:8760"
    monkeypatch.setenv("WORLD_HOUSE_SHELL_ORIGIN", shell_origin)
    fixture = fixture_app("ep_9031")
    simulator = create_app(tmp_path / "world.db", operator_enabled=True,
                           bind_host="127.0.0.1", broker_enabled=False)

    async def exercise(viewer):
        clock = Clock()
        hub = Scenario(tmp_path, clock, episode="ep_9031", transport=httpx2.ASGITransport(app=fixture))
        install_birthday(hub)
        world = simulator.state.world
        world.clock = clock
        loop = asyncio.get_running_loop()

        def publish_to_hub(topic, payload, *, qos, retain):
            assert qos == 1 and not retain
            suffix = topic.removeprefix(hub.mqtt.prefix + "/")
            loop.call_soon_threadsafe(hub.world.emit, suffix, json.loads(payload))

        protocol = DeviceProtocol(world, hub.mqtt.prefix, publish_to_hub)

        async def publish_to_world(topic, payload, *, qos, retain):
            protocol.receive(topic, payload, qos=qos, retained=retain)

        simulator.state.protocol = protocol
        hub.mqtt.client.publish = publish_to_world
        hub.boot()
        try:
            await hub.reconcile()
            protocol.dispatch(world.home_event, "guests_arrive")
            await hub.cycle()
            before = world.read(LIGHT)["values"]["color"]
            assert before == {"hue": 330, "saturation": 45, "brightness": 70}
            clock.advance(minutes=10)
            page = viewer.get("/sim/viewer", params={"fragment": "true"}).raise_for_status()
            markers = ElementTree.fromstring(page.text).find(".//div[@id='viewer-markers']")
            light = markers.find(".//div[@data-device='light_01']")
            assert json.loads(markers.get("data-person-names")) == ["엄마", "아빠", "지아", "손님"]
            yellow = next(action for action in json.loads(light.get("data-person-actions")) if action["key"] == "color_yellow")
            assert yellow["label"] == "조명 색 바꾸기 · 노랑 빛"
            assert markers.get("data-person-shell-origin") == shell_origin
            endpoint = markers.get("data-person-endpoint")
            body = {"person": "엄마", "control": yellow["key"]}
            params = {"target": light.get("data-person-target")}
            rejected = viewer.post(endpoint, params=params, data=body,
                                   headers={"Origin": "http://127.0.0.1:8761", "Accept": "application/json"})
            assert rejected.status_code == 403
            assert "access-control-allow-origin" not in rejected.headers
            assert world.read(LIGHT)["values"]["color"] == before
            response = await asyncio.to_thread(
                viewer.post, endpoint, params=params, data=body,
                headers={"Origin": shell_origin, "Accept": "application/json"},
            )
            assert response.raise_for_status().json() == {"applied": True}
            assert response.headers["access-control-allow-origin"] == shell_origin
            read_back = viewer.get("/sim/snapshot").raise_for_status().json()
            reading = next(device for device in read_back["devices"] if device["logical_id"] == "light_01")
            assert reading["observation"] == "current"
            assert reading["values"]["color"] == {"hue": 55, "saturation": 60, "brightness": 70}

            await hub.cycle()
            events = [event for batch in (await hub.receipts())["events"] for event in batch]
            changes = [event["payload"] for event in events
                       if event["type"] == "light.changed" and event["source"] == "light_01"]
            assert changes[-1] == {
                "property": "color", "from": before, "to": reading["values"]["color"], "by": "user",
            }
        finally:
            await hub.close()

    with TestClient(fixture), TestClient(simulator, base_url="http://127.0.0.1:8730") as viewer:
        asyncio.run(exercise(viewer))


@pytest.mark.provisional
def test_person_stops_running_cleaner_and_fixture_updates_card(tmp_path):
    fixture = fixture_app(scene_controls=True, demo_mode=True)
    simulator = create_app(tmp_path / "world.db", operator_enabled=True,
                           bind_host="127.0.0.1", broker_enabled=False)

    async def exercise(server, operator):
        assert server.post(SELECT, json={"episode_id": "ep_9031"}).status_code == 202
        assert upload(server, "cleaner-panel-stop").status_code == 202
        finish_judgment(server)
        plan, = server.get(PLANS).raise_for_status().json()["plans"]
        cleaning = next(task for task in plan["tasks"] if task["task_id"] == "t_clean#1")
        due = cleaning["trigger"]["time"]
        assert server.post(CLOCK, json={"set_to": due}).status_code == 200

        clock = Clock(due)
        hub = Scenario(tmp_path, clock, episode="ep_9031", transport=httpx2.ASGITransport(app=fixture))
        install_birthday(hub)
        world = simulator.state.world
        world.clock = clock
        loop = asyncio.get_running_loop()

        def publish_to_hub(topic, payload, *, qos, retain):
            assert qos == 1 and not retain
            suffix = topic.removeprefix(hub.mqtt.prefix + "/")
            loop.call_soon_threadsafe(hub.world.emit, suffix, json.loads(payload))

        protocol = DeviceProtocol(world, hub.mqtt.prefix, publish_to_hub)

        async def publish_to_world(topic, payload, *, qos, retain):
            protocol.receive(topic, payload, qos=qos, retained=retain)

        hub.mqtt.client.publish = publish_to_world
        simulator.state.protocol = protocol
        hub.boot()

        def card_line():
            card, = server.get(CARDS).raise_for_status().json()["cards"]
            return next(line for line in card["lines"] if line["task_id"] == cleaning["task_id"])

        try:
            await hub.reconcile()
            await hub.cycle()
            running = world.read(CLEANER)
            assert running["job_id"] and running["values"]["in_use"]
            assert card_line()["state"] == "running"

            assert server.post(CLOCK, json={"set_to": clock.advance(seconds=1)}).status_code == 200
            await asyncio.to_thread(press, operator, CLEANER, world.profile.demo_people[0].name, "stop_clean")
            stopped = world.read(CLEANER)["values"]
            assert (stopped["clean"], stopped["in_use"], stopped["job_status"]) == (None, False, "stopped")

            await hub.cycle()
            receipts = await hub.receipts()
            user_events = [
                event for batch in receipts["events"] for event in batch
                if event["source"] == "cleaner_01" and event["payload"]["by"] == "user"
            ]
            assert any(event["type"] == "cleaner.stopped" for event in user_events)
            state = card_line()["state"]
            runs = [
                result["status"] for result in receipts["executions"]
                if result["task_id"] == cleaning["task_id"] and result["kind"] == "run"
            ]
            if (state == "unknown" and runs == ["running", "unknown"]
                    and [event["type"] for event in user_events] == ["cleaner.stopped"]):
                pytest.xfail("Fixture user_changed requires a .changed event after a completed run")
            assert state == "user_changed"
        finally:
            await hub.close()

    with TestClient(fixture, headers=HEADERS) as server, TestClient(simulator) as operator:
        asyncio.run(exercise(server, operator))


@pytest.mark.parametrize(
    ("profile", "target", "control", "label", "changed", "local"),
    [
        ("ep_9031", LIGHT, "color_yellow", "조명 색 바꾸기",
         {"color": {"hue": 55, "saturation": 60, "brightness": 70}}, True),
        ("ep_9031", "mqtt:display_01", "calm", "음악 바꾸기",
         {"play_mood": {"scene": "calm"}}, True),
        ("ep_9120", "mqtt:speaker_01", "music_calm", "음악 바꾸기",
         {"play": {"playlist": "calm", "volume": 30}}, False),
    ],
)
def test_panel_personalisation_publishes_an_observed_change(tmp_path, profile, target, control, label, changed, local):
    app = create_app(
        tmp_path / "world.db", profile=load_profile(DEFAULT_PROFILE.with_name(f"{profile}.json")),
        operator_enabled=True, bind_host="127.0.0.1", broker_enabled=False,
    )
    with TestClient(app) as client:
        world = app.state.world
        person = world.profile.demo_people[0]
        assert label in client.get("/operator").raise_for_status().text
        wire = Wire(world)
        app.state.protocol = wire.protocol
        press(client, target, person.name, control)
        (_, signal, _, _), = wire.frames
        assert signal["event_type"].endswith(".changed")
        assert signal["local_operation"] is local
        assert signal["operation_id"] is None
        for key, value in changed.items():
            assert world.read(target)["values"][key] == value
            assert signal["values"][key] == value
