from uuid import uuid4
from xml.etree import ElementTree

import pytest
from conftest import Wire, fixture_json
from fastapi.testclient import TestClient
from spira_contracts.devices import Command, Devices
from spira_simulator.api import create_app
from spira_simulator.profile import DEFAULT_PROFILE


@pytest.fixture(params=["ep_9031", "ep_9120"])
def demo(request, tmp_path, monkeypatch):
    episode = request.param
    monkeypatch.setenv("WORLD_PROFILE", str(DEFAULT_PROFILE.with_name(f"{episode}.json")))
    token = uuid4().hex
    app = create_app(
        tmp_path / "world.db",
        broker_enabled=False,
        operator_enabled=True,
        operator_token=token,
    )
    with TestClient(app) as client:
        yield episode, client, ("operator", token), Wire(app.state.world)


def test_sim_at22_lg_account_lists_the_loaded_profiles_lg_devices(demo):
    episode, client, auth, _ = demo
    path = "/lg/devices"
    assert client.get(path).status_code == 401
    assert client.get(path, auth=("other", auth[1])).status_code == 401
    response = client.get(path, auth=auth).raise_for_status()
    assert response.headers["Cache-Control"] == "no-store"

    labels = {
        "cleaner_01": "청소기",
        "oven_01": "오븐",
        "fridge_01": "냉장고",
        "air_purifier_01": "공기청정기",
    }
    if episode == "ep_9031":
        labels.update(
            display_01="TV",
            cooktop_01="인덕션",
            dishwasher_01="식기세척기",
            washer_01="세탁기",
        )
    else:
        labels["speaker_01"] = "스피커"
    inventory = Devices.model_validate(fixture_json(f"{episode}/devices.json"))
    expected = []
    for device in inventory.devices:
        if device.id not in labels:
            continue
        commands = list(device.commands)
        if device.id == "fridge_01":
            commands.append(Command(cmd="clear_notice"))
        expected.append(
            {
                "id": device.id,
                "type": device.type,
                "label": labels[device.id],
                "commands": [
                    {
                        **command.model_dump(mode="json"),
                        "basis": "sdk"
                        if command.cmd in {"clean", "mode", "wind_strength", "delayed_start"}
                        else "lg_assumed",
                    }
                    for command in commands
                ],
                "never": device.never,
            }
        )
    assert response.json() == expected


def test_sim_at23_notice_clear_is_observed_on_mqtt_and_the_test_home(demo):
    _, client, _, wire = demo
    fridge = "mqtt:fridge_01"
    fragment = "/sim/viewer?fragment=true"

    def fridge_tile():
        view = ElementTree.fromstring(client.get(fragment).raise_for_status().text)
        return view.find('.//div[@data-device="fridge_01"]/article')

    text = "냉장 보관 안내"
    receipt, (shown,) = wire.command(fridge, {"show_notice": text})
    assert receipt["status"] == "ACCEPTED"
    assert shown["operation_id"] == receipt["operation_id"]
    assert fridge_tile().findtext('p[@class="device-value"]') == text

    desired = {"show_notice": None}
    receipt, (cleared,) = wire.command(fridge, desired, operation_id="op_clear")
    assert receipt == {"status": "ACCEPTED", "operation_id": "op_clear", "job_id": None}
    assert cleared["event_type"] == "fridge.changed"
    assert cleared["operation_id"] == "op_clear"
    assert cleared["local_operation"] is False
    assert cleared["values"]["show_notice"] is None
    readback = wire.read(fridge)
    assert readback["values"]["show_notice"] is None
    assert readback["revisions"] == cleared["revisions"] != shown["revisions"]
    assert fridge_tile().findtext('p[@class="device-value"]') == "평소 화면"
    assert text not in client.get(fragment).text

    wire.command(fridge, {"show_notice": "새 안내"})
    repeated, signals = wire.command(fridge, desired, operation_id="op_clear")
    assert repeated == receipt and signals == []
    assert wire.read(fridge)["values"]["show_notice"] == "새 안내"


def test_sim_at24_never_actions_appear_as_locked_on_their_device_tiles(demo):
    episode, client, _, _ = demo
    inventory = Devices.model_validate(fixture_json(f"{episode}/devices.json"))
    view = ElementTree.fromstring(
        client.get("/sim/viewer?fragment=true").raise_for_status().text
    )
    action_labels = {"purchase": "구매", "heat": "가열", "start": "시작", "off": "끄기"}
    for device in inventory.devices:
        tile = view.find(f'.//div[@data-device="{device.id}"]/article')
        locked = tile.findall('.//li[@data-locked="true"]')
        assert [
            row.find('span[@aria-hidden="true"]').tail.strip() for row in locked
        ] == [action_labels[action] for action in device.never]
        assert all(
            row.findtext('span[@class="command-basis"]') == "하지 않아요"
            for row in locked
        )
