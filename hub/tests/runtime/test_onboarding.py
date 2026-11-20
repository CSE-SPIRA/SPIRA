"""HUB-AT21 and HUB-AT22 through Hub HTTP and a fake Simulator HTTP peer."""

import asyncio
from base64 import b64encode
from uuid import uuid4

import httpx2 as httpx

from hub.spira_hub.dashboard import create_app

from .peers import Clock, Scenario, Stub, action, fixture, light_config, task

PATH = "/home/onboarding/devices"
HUB_HEADERS = {"X-API-Key": fixture("household.created.json")["hub_api_key"]}
LG_DEVICES = [
    {
        "id": "oven_01", "type": "oven", "label": "오븐",
        "commands": [
            {"cmd": "set_cook_standby", "basis": "sdk", "value_schema": {
                "temp_c": {"range": [40, 250], "default": 180},
                "minutes": {"range": [1, 180], "default": 20},
            }},
            {"cmd": "start", "basis": "lg_assumed", "value_schema": None},
        ],
        "never": ["start"],
    },
]


class TestServerPeer(Stub):
    __test__ = False

    def __init__(self, clock):
        super().__init__(clock)
        self.registrations = []
        self.upload_down = False

    async def respond(self, request):
        if request.url.path.endswith("/devices"):
            if self.upload_down:
                return httpx.Response(503)
            self.registrations.append(await request.aread())
        return await super().respond(request)


class TestLGPeer:
    __test__ = False

    def __init__(self):
        self.requests = 0
        self.down = False
        password = uuid4().hex
        self.authorization = "Basic " + b64encode(f"operator:{password}".encode()).decode()
        self.http = httpx.AsyncClient(
            base_url="http://simulator", auth=("operator", password),
            transport=httpx.MockTransport(self.respond),
        )

    def respond(self, request):
        self.requests += 1
        assert (request.method, request.url.path) == ("GET", "/lg/devices")
        assert request.headers["Authorization"] == self.authorization
        assert "X-API-Key" not in request.headers
        return httpx.Response(503) if self.down else httpx.Response(200, json=LG_DEVICES)

    def client(self, hub):
        app = create_app(hub.runtime, hub_key=HUB_HEADERS["X-API-Key"], lg_http=self.http)
        return httpx.AsyncClient(base_url="http://hub", transport=httpx.ASGITransport(app=app))


def row(device, *commands, room=None, label=None):
    return {"id": device, "room": room, "label": label, "delegated_commands": list(commands)}


def settings(device):
    return device["stored"]


def test_hub_at21_at22_onboarding(tmp_path):
    async def exercise():
        clock = Clock()
        server = TestServerPeer(clock)
        lg = TestLGPeer()
        hub = Scenario(tmp_path, clock, stub=server)
        light, binding, native = light_config()
        hub.write([light], {"light_01": binding})
        hub.world.add(*native)
        hub.world.add("mqtt:oven_01", "oven", {"preset": None}, ["set_cook_standby"])
        hub.boot()
        await hub.reconcile()
        initial_revision = server.registry["revision"]

        async with lg.http, lg.client(hub) as app:
            assert (await app.get(PATH)).json() == {
                "code": "unauthorized", "message": "Household Hub key required",
            }
            denied = await app.put(PATH, headers={"X-API-Key": "wrong"}, json={"devices": []})
            assert denied.status_code == 401 and lg.requests == 0

            found = await app.get(PATH, headers=HUB_HEADERS)
            assert found.status_code == 200
            oven, lamp = found.json()["devices"]
            assert oven == {
                **LG_DEVICES[0], "room": None, "source": "lg_account",
                "stored": {"room": None, "label": None, "delegated_commands": []},
            }
            assert lamp == {
                "id": "light_01", "type": "light", "label": None, "room": "거실",
                "source": "installation", "never": [],
                "commands": [dict(command, basis="standard") for command in light["commands"]],
                "stored": {"room": "거실", "label": None, "delegated_commands": ["color", "color_temp"]},
            }

            for invalid in (
                row("oven_01", "bogus"), row("oven_01", "start"), row("missing", "off"),
            ):
                refused = await app.put(PATH, headers=HUB_HEADERS, json={
                    "devices": [row("light_01", room="안방"), invalid],
                })
                assert refused.status_code == 422
                assert refused.json()["code"] == "validation_error"
            assert len(server.registrations) == 1
            assert (await app.get(PATH, headers=HUB_HEADERS)).json() == found.json()

            changes = [row("oven_01", "set_cook_standby", room="주방", label="새 오븐"),
                       row("light_01", room=None, label="현관 조명")]
            accepted = await app.put(PATH, headers=HUB_HEADERS, json={"devices": changes})
            assert accepted.status_code == 200
            assert accepted.json() == {"revision": initial_revision + 1}
            assert len(server.registrations) == 2
            by_id = {device["id"]: device for device in server.registry["devices"]}
            assert by_id["oven_01"]["commands"] == [
                {k: v for k, v in LG_DEVICES[0]["commands"][0].items() if k != "basis"},
            ]
            assert by_id["oven_01"]["never"] == ["start"]
            assert by_id["light_01"]["commands"] == []
            assert by_id["light_01"]["room"] is None

            await hub.shutdown()
            hub.boot()
            await hub.reconcile()
            async with lg.client(hub) as restarted:
                result = await restarted.get(PATH, headers=HUB_HEADERS)
            oven, lamp = result.json()["devices"]
            assert oven["room"] is None and lamp["room"] == "거실"
            assert [settings(oven), settings(lamp)] == [
                {key: value for key, value in edit.items() if key != "id"} for edit in changes
            ]
            assert server.registry["revision"] == initial_revision + 1

            # The new device's delegation reaches normal plan admission and dispatch.
            value = {"temp_c": 170, "minutes": 20}
            server.advance(task(clock, action("oven_01", "set_cook_standby", value)),
                           task(clock, action(), n=2))
            await hub.reconcile()
            await hub.cycle()
            assert server.acks[-1]["rejected_tasks"] == [
                {"task_id": "t_test#2", "reason": "unsupported_cmd"},
            ]
            assert [command["desired"] for command in hub.world.commands] == [{"preset": value}]
            assert [result["status"] for result in server.executions] == ["completed"]
            await hub.close()

    asyncio.run(exercise())


def test_onboarding_retries_saved_revision_after_server_upload_failure(tmp_path):
    async def exercise():
        clock = Clock()
        server = TestServerPeer(clock)
        lg = TestLGPeer()
        hub = Scenario(tmp_path, clock, stub=server)
        light, binding, _ = light_config()
        hub.write([light], {"light_01": binding})
        hub.boot()
        await hub.reconcile()
        old_revision = server.registry["revision"]
        update = {"devices": [row("light_01", "color_temp", label="조명")]}

        async with lg.http, lg.client(hub) as app:
            lg.down = True
            assert (await app.get(PATH, headers=HUB_HEADERS)).status_code == 502
            assert (await app.put(PATH, headers=HUB_HEADERS, json=update)).status_code == 502
            assert len(server.registrations) == 1

            lg.down = False
            server.upload_down = True
            response = await app.put(PATH, headers=HUB_HEADERS, json=update)
            assert response.status_code == 502
            assert response.json()["message"] == "Device settings saved; Server upload pending"
            assert server.registry["revision"] == old_revision
            await hub.shutdown()
            hub.boot()
            server.upload_down = False
            await hub.reconcile()
            assert server.registry["revision"] == old_revision + 1
            assert len(server.registrations) == 2
            assert server.registry["devices"][0]["label"] == "조명"
            assert [c["cmd"] for c in server.registry["devices"][0]["commands"]] == ["color_temp"]
            await hub.close()

    asyncio.run(exercise())
