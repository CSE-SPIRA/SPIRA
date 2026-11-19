"""HUB-AT19 through the same HTTP surface used by the App, Hub, and judge."""

from copy import deepcopy
from urllib.parse import quote

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from . import create_app
from .api import LABEL, LABEL_HEADER
from .replay import CONTRACTS, FIXTURES, read_json

SCHEMAS = Registry().with_resources(
    (schema.name, Resource.from_contents(read_json(schema)))
    for schema in (CONTRACTS / "schemas").glob("*.json")
)
OPERATIONS = {}
for api in ("app", "hub"):
    document = yaml.safe_load(
        (CONTRACTS / "openapi" / f"{api}.yaml").read_text(encoding="utf-8")
    )
    for path, methods in document["paths"].items():
        for method, operation in methods.items():
            OPERATIONS[method.upper(), path] = (operation, document["components"])

APP_HOUSEHOLD = "/v1/households/{household_id}"
HUB_DEVICES = "/v1/hub/households/{household_id}/devices"
EPISODE = "/v1/episodes/{episode_id}"
ACK = "/v1/hub/plans/{plan_id}/ack"
REACTIONS = "/v1/cards/{card_id}/reactions"
ONBOARDING = read_json(FIXTURES / "ep_9031" / "household.created.json")
HEADERS = {"Authorization": "Bearer fixture", "X-API-Key": ONBOARDING["hub_api_key"]}


def check_schema(payload, schema):
    schema = dict(schema)
    if "$ref" in schema:
        schema["$ref"] = schema["$ref"].removeprefix("../schemas/")
    elif "properties" in schema:
        schema["properties"] = {
            key: {**entry, "$ref": entry["$ref"].removeprefix("../schemas/")}
            if "$ref" in entry
            else entry
            for key, entry in schema["properties"].items()
        }
    Draft202012Validator(schema, registry=SCHEMAS).validate(payload)


class ContractClient:
    def __init__(self, client, episode_id, covered):
        self.client = client
        self.episode_id = episode_id
        self.household = self.fixture("plan.v1.json")["household_id"]
        self.covered = covered

    def fixture(self, name):
        return read_json(FIXTURES / self.episode_id / name)

    def request(
        self, method, template, status=200, *, valid_request=True, path=None, **kwargs
    ):
        operation, components = OPERATIONS[method, template]
        path_values = {
            "household_id": self.household,
            "episode_id": self.episode_id,
            "plan_id": self.episode_id,
            **(path or {}),
        }
        url = template.format(
            **{key: quote(value, safe="") for key, value in path_values.items()}
        )
        if valid_request and "requestBody" in operation:
            content = operation["requestBody"]["content"]
            if "application/json" in content:
                check_schema(kwargs["json"], content["application/json"]["schema"])
            else:
                check_schema(
                    {
                        **kwargs["data"],
                        "images": [part[1][0] for part in kwargs["files"]],
                    },
                    content["multipart/form-data"]["schema"],
                )

        result = self.client.request(method, url, **kwargs)
        assert result.status_code == status, result.text
        assert result.headers[LABEL_HEADER] == LABEL
        schema_response = operation["responses"][str(status)]
        if "$ref" in schema_response:
            schema_response = components["responses"][
                schema_response["$ref"].split("/")[-1]
            ]
        self.covered.add((method, template))
        if "content" not in schema_response:
            assert result.content == b""
            return None
        body = result.json()
        check_schema(body, schema_response["content"]["application/json"]["schema"])
        return body

    def pull(self):
        return self.request(
            "GET", "/v1/hub/plans", params={"household": self.household}
        )

    def register_devices(self, devices=None):
        if devices is None:
            manifest = self.fixture("manifest.json")
            devices = self.fixture(manifest["devices"])
        assert self.request("PUT", HUB_DEVICES, json=devices) == {
            "revision": devices["revision"]
        }

    def cards(self, **params):
        return self.request("GET", f"{APP_HOUSEHOLD}/cards", params=params)

    def ack(self, version=1):
        self.request(
            "POST",
            ACK,
            204,
            json={
                "plan_version": version,
                "status": "admitted",
                "rejected_tasks": [],
            },
        )

    def react(self, body, *, card_id="nc_331", status=200):
        return self.request(
            "POST", REACTIONS, status, path={"card_id": card_id}, json=body
        )

    def receive_log(self):
        receipts = self.client.get("/_fixture/receipts")
        assert receipts.status_code == 200
        assert receipts.headers[LABEL_HEADER] == LABEL
        return receipts.json()


@pytest.fixture
def peer():
    def make(episode_id, covered=None):
        return ContractClient(
            TestClient(create_app(episode_id), headers=HEADERS),
            episode_id,
            covered if covered is not None else set(),
        )

    return make


def share_order(client, status, source_id):
    return client.request(
        "POST",
        "/v1/orders",
        status,
        data={"household_id": client.household, "source_id": source_id},
        files=[("images", ("capture.png", b"fixture upload", "image/png"))],
    )


def replay_birthday(client):
    request = client.request
    fixture = client.fixture
    assert request("GET", "/health") == {"status": "ok"}
    assert (
        request("POST", "/v1/households", 201, json=fixture("household.create.json"))
        == ONBOARDING
    )
    assert request("PUT", f"{APP_HOUSEHOLD}/profile", json={"household_types": []}) == {
        "household_id": client.household,
        "household_types": [],
    }
    committed = fixture("household.create.json")
    assert request("PUT", f"{APP_HOUSEHOLD}/profile", json=committed) == {
        "household_id": client.household,
        "household_types": committed["household_types"],
    }
    blocked = read_json(CONTRACTS / "check/bad/household_blocked/household.create.json")
    assert (
        request("PUT", f"{APP_HOUSEHOLD}/profile", 422, json=blocked)["code"]
        == "household_types_invalid"
    )
    calendar = fixture("calendar.json")
    assert request("PUT", f"{APP_HOUSEHOLD}/calendar", 202, json=calendar) == {
        "accepted": len(calendar["events"]),
    }
    assert share_order(client, 202, "birthday-share") == {
        "episode_id": "ep_9031",
        "status": "received",
    }
    assert share_order(client, 200, "birthday-share") == {
        "episode_id": "ep_9031",
        "status": "received",
    }

    assert request("GET", EPISODE)["status"] == "notified"
    order_edit = {
        "items": [
            {key: item[key] for key in ("item_id", "name", "qty")}
            for item in fixture("episode.json")["items"]
        ]
    }
    assert request("PUT", f"{EPISODE}/order", 202, json=order_edit) == {
        "episode_id": "ep_9031",
        "status": "received",
    }
    history = request("GET", f"{APP_HOUSEHOLD}/episodes")
    assert history["episodes"][0]["episode_id"] == "ep_9031"
    assert request(
        "GET",
        f"{APP_HOUSEHOLD}/episodes",
        params={
            "limit": 1,
            "before": history["episodes"][0]["shared_at"],
        },
    ) == {"episodes": [], "next_before": None}

    client.register_devices()
    assert client.pull()["plans"] == [fixture("plan.v1.json")]
    initial = client.cards()
    assert initial["cards"] == [fixture("card.v1.json")]
    assert client.cards(since=initial["server_time"])["cards"] == []
    assert request("GET", f"{EPISODE}/rationale") == fixture("rationale.json")
    request("POST", ACK, 204, json=fixture("ack.v1.json"))
    assert fixture("reactions.json") == [{"reaction": "line_off", "task_id": "t_clean#1"}]
    updated = client.react(fixture("reactions.json")[0])
    lines = {line["task_id"]: line for line in updated["lines"]}
    assert lines["t_clean#1"]["state"] == "off"
    assert lines["t_clean#1"]["checked"] is False
    assert lines["t_safe#2"]["checked"] is True
    assert updated["notify"] is False
    assert client.cards(since=initial["server_time"])["cards"] == [updated]
    plans = client.pull()["plans"]
    assert plans == [fixture("plan.v2.json")]
    assert plans[0]["cancelled"] == [{"task_id": "t_clean#1", "restore": False}]
    assert next(task for task in plans[0]["tasks"] if task["task_id"] == "t_safe#2")["protective"] is True
    client.ack(2)

    events = fixture("events.json")
    executions = fixture("executions.json")
    assert request("POST", "/v1/hub/events", json=[events[0]]) == {
        "accepted": [events[0]["event_id"]],
        "rejected": [],
        "plans_changed": True,
    }
    assert client.pull() == fixture("pull.json")
    client.ack(3)
    # Interleave the remaining C-3 and C-4 packets in the committed timeline order.
    packets = sorted(
        [("/v1/hub/events", event) for event in events[1:]]
        + [("/v1/hub/executions", result) for result in executions],
        key=lambda packet: packet[1]["at"],
    )
    for route, body in packets:
        if route == "/v1/hub/events":
            assert request("POST", route, json=[body]) == {
                "accepted": [body["event_id"]],
                "rejected": [],
                "plans_changed": False,
            }
        else:
            assert request("POST", route, json=body) == {"duplicate": False}

    assert request("GET", EPISODE) == fixture("episode.json")
    assert client.cards(since=updated["updated_at"])["cards"] == [
        fixture("card.final.json")
    ]
    assert client.cards()["cards"] == []
    assert client.pull()["plans"] == []
    assert request("GET", f"{EPISODE}/rationale") == fixture("rationale.json")
    memory = request("GET", f"{APP_HOUSEHOLD}/memory")
    assert memory == fixture("memory.json")
    case_id = memory["intents"][0]["episodes"][0]["case_id"]
    request(
        "DELETE", f"{APP_HOUSEHOLD}/memory/{{case_id}}", 204, path={"case_id": case_id}
    )
    assert request("GET", f"{APP_HOUSEHOLD}/memory")["intents"] == []

    assert request("POST", "/v1/hub/events", json=[events[0]]) == {
        "accepted": [events[0]["event_id"]],
        "rejected": [],
        "plans_changed": False,
    }
    assert request("POST", "/v1/hub/executions", json=executions[-1]) == {
        "duplicate": True
    }
    assert client.receive_log() == {
        "events": [[event] for event in [*events, events[0]]],
        "executions": [*executions, executions[-1]],
    }


def replay_groceries(client):
    assert share_order(client, 202, "grocery-share")["episode_id"] == "ep_9150"
    client.register_devices()
    plans = client.pull()["plans"]
    assert plans == [client.fixture("plan.v1.json")]
    client.ack()
    episode = client.request("GET", EPISODE)
    assert episode == client.fixture("episode.json")
    assert client.cards()["cards"] == []
    rationale = client.request("GET", f"{EPISODE}/rationale")
    assert rationale == client.fixture("rationale.json")
    assert not rationale["intents"] and rationale["none_reason"]
    strawberry = next(item for item in episode["item_tasks"] if item["task_id"] == "t_fridge#2")
    assert strawberry in rationale["item_tasks"]
    task = next(task for task in plans[0]["tasks"] if task["task_id"] == strawberry["task_id"])
    assert task["trigger"]["released"] is False
    assert task["actions"][0]["value"] == strawberry["text"]
    birthday = read_json(FIXTURES / "ep_9031" / "episode.json")
    assert strawberry["text"] != next(item["text"] for item in birthday["item_tasks"]
                                     if item["item"] == strawberry["item"])
    paused = client.request("POST", f"{APP_HOUSEHOLD}/pause", json={"paused": True})
    assert paused == {"household_id": client.household, "paused": True}
    pull = client.pull()
    plan = pull["plans"][0]
    assert pull["paused"] is True
    assert plan["plan_version"] == 2
    assert plan["tasks"] == []
    assert plan["cancelled"] == [
        {"task_id": task["task_id"], "restore": False}
        for task in client.fixture("plan.v1.json")["tasks"]
    ]
    assert share_order(client, 202, "paused-share")["status"] == "paused_skip"
    client.request("POST", f"{APP_HOUSEHOLD}/pause", json={"paused": False})
    assert client.pull() == {**pull, "paused": False}
    assert client.receive_log() == {"events": [], "executions": []}


def replay_held(client):
    fixture = client.fixture
    client.register_devices()
    assert client.pull()["plans"] == [fixture("plan.v1.json")]
    client.ack()
    episode = client.request("GET", EPISODE)
    assert episode["status"] == "held"
    assert episode["items"] == episode["item_tasks"] == []
    held = client.cards()
    assert held["cards"] == [fixture("card.held.json")]
    assert client.request(
        "PUT", f"{APP_HOUSEHOLD}/calendar", 202, json={"events": []}
    ) == {"accepted": 0}
    assert client.pull()["plans"] == [fixture("plan.v1.json")]
    calendar = fixture("calendar.json")
    for _ in range(2):
        assert client.request(
            "PUT", f"{APP_HOUSEHOLD}/calendar", 202, json=calendar
        ) == {"accepted": 1}
        assert client.pull()["plans"] == [fixture("plan.v2.json")]
    assert client.cards(since=held["server_time"])["cards"] == [
        fixture("card.found.json")
    ]
    assert client.request("GET", EPISODE)["status"] == "notified"
    client.ack(2)
    assert client.request("GET", f"{APP_HOUSEHOLD}/memory")["intents"] == []
    assert client.request("GET", f"{EPISODE}/rationale", 404)["code"] == "not_found"
    assert client.receive_log() == {"events": [], "executions": []}


def test_hub_at19(peer):
    covered = set()
    replay_birthday(peer("ep_9031", covered))
    replay_groceries(peer("ep_9150", covered))
    replay_held(peer("ep_9120", covered))
    assert covered == set(OPERATIONS)


def test_line_on_and_stop_derive_versions_from_fixture_actions(peer):
    client = peer("ep_9031")
    reaction = client.fixture("reactions.json")[0]
    old_id = reaction["task_id"]
    initial = client.pull()["plans"][0]
    client.react(reaction)
    off = client.pull()["plans"][0]
    enabled = client.react({"reaction": "line_on", "task_id": old_id})
    plan = client.pull()["plans"][0]
    new_id = next(
        line["task_id"]
        for line in enabled["lines"]
        if line["task_id"] not in {task["task_id"] for task in initial["tasks"]}
    )
    original = next(task for task in initial["tasks"] if task["task_id"] == old_id)
    assert plan["plan_version"] == off["plan_version"] + 1
    assert plan["cancelled"] == off["cancelled"]
    assert next(task for task in plan["tasks"] if task["task_id"] == new_id) == {
        **original,
        "task_id": new_id,
    }

    result = next(
        result
        for result in client.fixture("executions.json")
        if result["kind"] == "run" and result["task_id"] == "t_safe#2"
    )
    assert client.request("POST", "/v1/hub/executions", json=result) == {
        "duplicate": False
    }
    assert (
        client.react({"reaction": "line_on", "task_id": result["task_id"]}, status=409)[
            "code"
        ]
        == "line_started"
    )
    stopped = client.react({"reaction": "stop"})
    assert stopped["stopped"] is True
    assert stopped["buttons"] == []
    assert stopped["notify"] is False
    assert client.react({"reaction": "line_on", "task_id": new_id}) == stopped
    stop_plan = client.pull()["plans"][0]
    assert stop_plan["plan_version"] == plan["plan_version"] + 1
    assert stop_plan["tasks"] == [
        task for task in plan["tasks"] if task["source"] == "item"
    ]
    assert {item["task_id"]: item["restore"] for item in stop_plan["cancelled"]} == {
        task["task_id"]: task["task_id"] == result["task_id"]
        for task in initial["tasks"]
        if task["source"] == "situation"
    } | {new_id: False}


def test_calendar_keeps_a_held_line_off_until_it_is_explicitly_reenabled(peer):
    client = peer("ep_9120")
    card = client.fixture("card.held.json")
    task_id = card["lines"][0]["task_id"]
    client.react({"reaction": "line_off", "task_id": task_id}, card_id=card["card_id"])
    client.request(
        "PUT", f"{APP_HOUSEHOLD}/calendar", 202, json=client.fixture("calendar.json")
    )
    plan = client.pull()["plans"][0]
    assert task_id not in {task["task_id"] for task in plan["tasks"]}

    enabled = client.react(
        {"reaction": "line_on", "task_id": task_id}, card_id=card["card_id"]
    )
    line = enabled["lines"][0]
    assert line["task_id"] != task_id
    assert line["state"] == "scheduled"
    assert line["when"] == client.fixture("card.found.json")["lines"][0]["when"]
    assert client.pull()["plans"][0]["tasks"][-1]["task_id"] == line["task_id"]


@pytest.mark.parametrize("episode_id", ["ep_9150", "ep_9120"])
def test_a_package_from_before_the_order_keeps_item_work_waiting(peer, episode_id):
    client = peer(episode_id)
    pull = client.pull()
    event = read_json(FIXTURES / "ep_9031" / "events.json")[0]
    event["household_id"] = client.household
    assert (
        client.request("POST", "/v1/hub/events", json=[event])["plans_changed"] is False
    )
    assert client.pull() == pull
    assert client.receive_log() == {"events": [[event]], "executions": []}


def test_judge_receives_actual_bodies_and_retries(peer):
    client = peer("ep_9031")
    event = deepcopy(client.fixture("events.json")[2])
    event["event_id"] = "ev_judge"
    event["payload"]["by"] = "unknown"
    event["payload"]["judge_test_marker"] = {"observed": None}
    retry = deepcopy(event)
    retry["payload"]["by"] = "user"

    assert client.request("POST", "/v1/hub/events", json=[event, retry]) == {
        "accepted": ["ev_judge", "ev_judge"],
        "rejected": [],
        "plans_changed": False,
    }
    result = client.fixture("executions.json")[2]
    result["status"] = "running"
    result.pop("observed")
    assert client.request("POST", "/v1/hub/executions", json=result) == {
        "duplicate": False
    }
    assert client.receive_log() == {"events": [[event, retry]], "executions": [result]}
    assert peer("ep_9031").receive_log() == {"events": [], "executions": []}


def test_invalid_requests_use_contract_error_bodies(peer):
    client = peer("ep_9031")
    request = client.request
    assert (
        request("GET", EPISODE, 401, headers={"Authorization": ""})["code"]
        == "unauthorized"
    )
    event = client.fixture("events.json")[5]
    del event["payload"]["by"]
    batch = request("POST", "/v1/hub/events", json=[event], valid_request=False)
    assert batch["accepted"] == []
    assert batch["rejected"][0]["event_id"] == event["event_id"]
    assert batch["plans_changed"] is False

    result = client.fixture("executions.json")[0]
    result["status"] = (
        "blocked"  # Its fixture reason is null, which is invalid for blocked.
    )
    assert (
        request("POST", "/v1/hub/executions", 422, json=result, valid_request=False)[
            "code"
        ]
        == "validation_error"
    )
    assert client.receive_log() == {"events": [[event]], "executions": [result]}
    assert (
        request(
            "POST",
            REACTIONS,
            422,
            json={"reaction": "line_off"},
            valid_request=False,
            path={"card_id": "nc_331"},
        )["code"]
        == "validation_error"
    )

    devices = client.fixture("devices.json")
    devices["revision"] += 1
    client.register_devices(devices)
    assert client.pull()["devices_revision"] == devices["revision"]
    assert client.pull()["plans"] == [client.fixture("plan.v1.json")]
    assert (
        request("PUT", HUB_DEVICES, 409, json=client.fixture("devices.json"))["code"]
        == "stale_revision"
    )
    assert (
        request("GET", "/v1/hub/plans", 403, params={"household": "h_other"})["code"]
        == "forbidden"
    )
