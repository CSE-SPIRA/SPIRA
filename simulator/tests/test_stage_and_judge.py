import json
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

import httpx
import pytest
from conftest import LIGHT, OVEN, PLUG, Wire, fixture_json
from fastapi.testclient import TestClient
from spira_contracts.plan import Plan
from spira_simulator.api import create_app
from spira_simulator.profile import DEFAULT_PROFILE, Profile, load_profile, public_value
from spira_simulator.sources import JsonSource
from spira_simulator.world import DEVICE_SCHEMA, World

AUTH = ("operator", uuid4().hex)


class SourceStub:
    def __init__(self, body):
        self.body = body

    async def fetch(self):
        return self.body


def operator_app(tmp_path, **kwargs):
    return create_app(
        tmp_path / "world.db",
        operator_enabled=True,
        operator_token=AUTH[1],
        broker_enabled=False,
        **kwargs,
    )


def post(client, endpoint, **payload):
    response = client.post(endpoint, json=payload, auth=AUTH)
    response.raise_for_status()
    return response


def mock_http_source(monkeypatch, handle):
    actual_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: actual_client(
            transport=httpx.MockTransport(handle),
            **kwargs,
        ),
    )


@pytest.fixture
def captured_receipts():
    path = Path(__file__).with_name("fixtures") / "fixture_receipts.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_overlay_reads_authenticated_plan_and_fixture_executions(
    tmp_path, monkeypatch, captured_receipts
):
    fixture = "http://fixture.invalid"
    monkeypatch.setenv("WORLD_PLANS", f"{fixture}/v1/hub/plans?household=h_042")
    monkeypatch.setenv("WORLD_PLANS_TOKEN", "test-hub-key")
    monkeypatch.setenv("WORLD_EXECUTIONS", f"{fixture}/_fixture/receipts")

    def handle(request):
        assert request.method == "GET"
        if request.url.path == "/v1/hub/plans":
            assert request.url.params["household"] == "h_042"
            assert request.headers["X-API-Key"] == "test-hub-key"
            assert "Authorization" not in request.headers
            return httpx.Response(200, json=fixture_json("ep_9031/pull.json"))
        assert request.url.path == "/_fixture/receipts"
        return httpx.Response(200, json=captured_receipts)

    mock_http_source(monkeypatch, handle)
    with TestClient(operator_app(tmp_path)) as client:
        overlay = client.get("/sim/overlay").raise_for_status().json()

    assert overlay["errors"] == []
    assert overlay["preparation"] == []
    assert len(overlay["notices"]) == 2
    assert {
        (row["device"], row["status"], row["substrate"]) for row in overlay["restores"]
    } == {
        ("cooktop_01", "restored", "virtual"),
        ("plug_kettle", "restored", "virtual"),
        ("light_01", "skipped_user_changed", "virtual"),
        ("display_01", "restored", "virtual"),
    }


@pytest.mark.parametrize("from_hub", [False, True], ids=["fixture", "hub"])
def test_judge_reads_delivery_evidence(
    tmp_path, monkeypatch, captured_receipts, from_hub
):
    monkeypatch.setenv("WORLD_RECEIVED_URL", "http://fixture.invalid/_fixture/receipts")
    light, oven = [
        event
        for batch in captured_receipts["events"]
        for event in batch
        if event["payload"].get("by") == "user"
    ]
    if from_hub:
        monkeypatch.setenv("WORLD_HUB_STATE_URL", "http://hub.invalid/state")
        hub_rows = [
            {"packet": batch, "delivered": True, "delivery_error": None}
            for batch in captured_receipts["events"]
        ]
        pending = next(row for row in hub_rows if row["packet"] == [oven])
        pending.update(delivered=False, delivery_error="HTTP 503")

    def handle(request):
        assert request.method == "GET"
        if from_hub:
            assert request.url.host == "hub.invalid" and request.url.path == "/state"
            return httpx.Response(200, json={"events": hub_rows})
        assert request.url.path == "/_fixture/receipts"
        return httpx.Response(200, json=captured_receipts)

    mock_http_source(monkeypatch, handle)
    app = operator_app(tmp_path)
    url = "/operator/judge"
    with TestClient(app) as client:
        monkeypatch.setattr(
            app.state.world, "clock", lambda: datetime.fromisoformat(light["at"])
        )
        post(
            client,
            "/operator/device",
            target=LIGHT,
            actor="resident",
            values={"color": light["payload"]["to"]},
        )
        monkeypatch.setattr(
            app.state.world, "clock", lambda: datetime.fromisoformat(oven["at"])
        )
        post(client, "/operator/device", target=OVEN, actor="resident", start=True)
        result = client.get(url, auth=AUTH).raise_for_status().json()
        if from_hub:
            assert result["source"] == "hub_state"
            assert result["not_delivered"] == [
                {
                    "event_id": oven["event_id"],
                    "device": oven["source"],
                    "event_type": oven["type"],
                    "at": oven["at"],
                    "delivery_error": "HTTP 503",
                }
            ]
            assert [row["event_id"] for row in result["results"]] == [light["event_id"]]
            assert all(row["event_id"] != oven["event_id"] for row in result["unresolved"])
            pending.update(delivered=True, delivery_error=None)
            result = client.get(url, auth=AUTH).raise_for_status().json()

    assert result["source"] == ("hub_state" if from_hub else "fixture_receipts")
    assert result["not_delivered"] == []
    comparisons = [
        (row["event_id"], row["by"], row["verdict"]) for row in result["results"]
    ]
    assert comparisons == [
        (light["event_id"], "user", "match"),
        (oven["event_id"], "user", "match"),
    ]


def test_overlay_prefers_live_plans_and_uses_hub_task_stories_and_restoration(
    tmp_path, monkeypatch, captured_receipts
):
    monkeypatch.setenv("WORLD_HUB_STATE_URL", "http://hub.invalid/state")
    monkeypatch.setenv("WORLD_EXECUTIONS", "http://fixture.invalid/_fixture/receipts")
    monkeypatch.setenv("WORLD_PLANS", "http://fixture.invalid/plan")
    monkeypatch.setenv(
        "WORLD_PLANS_URL", "http://server.invalid/v1/hub/plans?household=h_042"
    )
    hub_key = uuid4().hex
    monkeypatch.setenv("WORLD_PLANS_TOKEN", hub_key)

    stories = {}
    restoration = []
    for record in captured_receipts["executions"]:
        task_id = record["task_id"]
        if record["kind"] == "run":
            story = stories.setdefault(
                task_id, {"task_id": task_id, "plan_id": record["plan_id"], "steps": []}
            )
            status = "dispatching" if record["device"] == "oven_01" else record["status"]
            story["steps"].append(
                {
                    "kind": "command",
                    "phase": "run",
                    "device": record["device"],
                    "at": record["at"],
                    "status": status,
                    "substrate": record["substrate"],
                }
            )
        else:
            delivered = task_id == "t_safe#2"
            restoration.append(
                {"packet": record, "delivered": delivered, "delivery_error": None}
            )

    def handle(request):
        assert request.method == "GET"
        if request.url.host == "server.invalid":
            assert request.url.path == "/v1/hub/plans"
            assert request.url.params["household"] == "h_042"
            assert request.headers["X-API-Key"] == hub_key
            return httpx.Response(200, json=fixture_json("ep_9031/pull.json"))
        assert request.url.host == "hub.invalid" and request.url.path == "/state"
        assert "X-API-Key" not in request.headers
        return httpx.Response(
            200, json={"task_stories": list(stories.values()), "restoration": restoration}
        )

    mock_http_source(monkeypatch, handle)
    with TestClient(operator_app(tmp_path)) as client:
        overlay = client.get("/sim/overlay").raise_for_status().json()

    assert overlay["errors"] == []
    assert [row["device"] for row in overlay["preparation"]] == ["oven_01"]
    assert len(overlay["notices"]) == 2
    assert {
        (row["device"], row["status"], row["substrate"], row["delivery"])
        for row in overlay["restores"]
    } == {
        ("cooktop_01", "restored", "virtual", "delivered"),
        ("plug_kettle", "restored", "virtual", "delivered"),
        ("light_01", "skipped_user_changed", "virtual", "not_delivered"),
        ("display_01", "restored", "virtual", "not_delivered"),
    }
    assert public_value(overlay)


@pytest.mark.provisional
def test_sim_at02_actor_matrix_provisional_class_a_and_received_c3(
    tmp_path, monkeypatch
):
    received = []
    app = operator_app(tmp_path, received_source=SourceStub(received))
    actors = [
        ("resident", "user", "match"),
        ("child", "user", "person-not-decision-maker"),
        ("guest", "user", "person-not-decision-maker"),
        ("external_automation", "unknown", "match"),
        ("device_self", "unknown", "match"),
        ("spira", "spira", "match"),
    ]

    with TestClient(app) as client:
        frames = []
        monkeypatch.setattr(
            app.state.protocol,
            "publish",
            lambda topic, payload, **kw: frames.append(
                (topic, json.loads(payload), kw),
            ),
        )
        prefix = app.state.protocol.prefix
        expected = []
        for class_a, target, logical_id, device_type in (
            (True, LIGHT, "light_01", "light"),
            (False, PLUG, "plug_kettle", "smart_plug"),
        ):
            for index, (actor, class_a_by, verdict) in enumerate(actors):
                value = (
                    {"color": {"kelvin": 2700 + index}}
                    if class_a
                    else {"power": bool(index % 2)}
                )
                if actor == "spira":
                    desired = (
                        {"color": {"kelvin": 3000}} if class_a else {"power": True}
                    )
                    app.state.protocol.receive(
                        f"{prefix}/command",
                        json.dumps(
                            {
                                "schema": DEVICE_SCHEMA,
                                "request_id": "rq_test",
                                "reply_to": f"{prefix}/reply/test/rq_test",
                                "operation_id": f"op_{device_type}",
                                "target": target,
                                "desired": desired,
                            }
                        ).encode(),
                        qos=1,
                        retained=False,
                    )
                else:
                    post(
                        client,
                        "/operator/device",
                        target=target,
                        actor=actor,
                        values=value,
                    )
                topic, signal, options = frames[-1]
                assert topic == f"{prefix}/events" and options == {
                    "qos": 1,
                    "retain": False,
                }
                assert (
                    signal["target"] == target
                    and signal["event_type"] == f"{device_type}.changed"
                )
                at_device = actor in {"resident", "child", "guest"}
                assert signal["local_operation"] == (class_a and at_device)
                assert bool(signal["operation_id"]) == (actor == "spira")
                by = class_a_by
                if not class_a and at_device:
                    by = "unknown"
                    verdict = "person-reported-unknown"
                at = (
                    datetime.fromisoformat(signal["occurred_at"])
                    .astimezone(UTC)
                    .isoformat()
                )
                event = {
                    "event_id": f"ev_{device_type}_{index}",
                    "household_id": "h_042",
                    "source": logical_id,
                    "type": signal["event_type"],
                    "at": at,
                    "payload": {
                        "by": by,
                        "property": next(iter(value)),
                        "from": None,
                        "to": value,
                    },
                }
                received.append(event)
                expected.append((event["event_id"], by, verdict, actor))

        wrong = {
            **received[3],
            "event_id": "ev_bad_attribution",
            "payload": {**received[3]["payload"], "by": "user"},
        }
        received.extend([received[-1], wrong])
        expected.append(
            (
                wrong["event_id"],
                "user",
                "non-person-reported-user",
                "external_automation",
            )
        )

        response = client.get("/operator/judge", auth=AUTH)
        response.raise_for_status()
        judged = response.json()
        assert judged["unresolved"] == []
        assert [
            (r["event_id"], r["by"], r["verdict"], r["truth"]["actor"])
            for r in judged["results"]
        ] == expected
        for path in (
            "/operator",
            "/operator/options",
            "/operator/ui.js",
            "/operator/judge",
            "/operator/truth",
        ):
            assert client.get(path).status_code == 401
        assert client.post("/operator/device", json={}).status_code == 401
        assert all(public_value(body) for _, body, _ in frames)
        assert public_value(client.get("/sim/snapshot").json())
        assert public_value(client.get("/sim/overlay").json())
        assert public_value(client.get("/health").json())


def test_judge_reads_http_receipt_and_only_joins_exact_device_type_and_time(
    tmp_path, monkeypatch
):
    source = JsonSource("http://fixture.invalid/received")
    app = operator_app(tmp_path, received_source=source)
    with TestClient(app) as client:
        post(
            client,
            "/operator/device",
            target=LIGHT,
            actor="resident",
            values={"power": True},
        )
        (fact,) = client.get("/operator/truth", auth=AUTH).json()
        event = {
            "event_id": "ev_read_at_fixture",
            "household_id": "h_042",
            "source": "light_01",
            "type": "light.changed",
            "at": fact["occurred_at"],
            "payload": {
                "by": "unknown",
                "property": "power",
                "from": False,
                "to": True,
            },
        }
        records = [
            event,
            {**event, "event_id": "ev_wrong_household", "household_id": "h_other"},
            {**event, "event_id": "ev_native_instead_of_logical", "source": LIGHT},
            {**event, "event_id": "ev_wrong_time", "at": "2026-10-17T15:00:00+09:00"},
            {**event, "event_id": "ev_wrong_type", "type": "light.started"},
            {
                **event,
                "event_id": "ev_unspecified_outcome",
                "payload": {**event["payload"], "by": "spira"},
            },
        ]
        calls = []

        def handle(request):
            calls.append((request.method, request.url.path))
            return httpx.Response(200, json=records)

        mock_http_source(monkeypatch, handle)
        result = client.get("/operator/judge", auth=AUTH).json()
        assert calls == [("GET", "/received")]
        assert [row["verdict"] for row in result["results"]] == [
            "person-reported-unknown"
        ]
        assert [row["reason"] for row in result["unresolved"]] == [
            "no_matching_truth"
        ] * 3 + ["undefined_attribution"]


def test_judge_counts_command_arrivals_by_marker_and_time(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(
        "spira_simulator.api.World", lambda path, profile: World(path, profile, clock)
    )
    marker_url = "/operator/judge/marker"
    counts_url = "/operator/judge/commands"
    plan = Plan.model_validate(fixture_json("ep_9150/plan.v1.json"))
    with TestClient(operator_app(tmp_path)) as client:
        wire = Wire(client.app.state.world)
        assert client.post(marker_url).status_code == 401
        assert client.get(counts_url).status_code == 401
        assert client.get(counts_url, auth=AUTH).status_code == 409
        assert client.get("/operator/judge", auth=AUTH).status_code == 503

        # A pre-marker dispatch shares the timestamp of the grocery notices.
        wire.command(LIGHT, {"power": False}, "op_prior")
        marker = post(client, marker_url).json()
        wire.command(LIGHT, {"power": False}, "op_prior")
        empty = client.get(counts_url, auth=AUTH).json()
        assert empty["total"] == {"notices": 0, "other_commands": 0}
        client.app.state.world.home_event("delivery")
        for task in plan.tasks:
            (action,) = task.actions
            payload = {"show_notice": action.value}
            target = f"mqtt:{action.device}"
            wire.command(target, payload, task.task_id)
            wire.command(target, payload, task.task_id)
        wire.read(LIGHT)
        clock.advance()
        to_time = clock.now.astimezone(UTC).isoformat()

        groceries = client.get(counts_url, auth=AUTH).json()
        assert groceries["window"]["start"] == marker["at"]
        assert groceries["total"] == {"notices": 2, "other_commands": 0}
        assert groceries["by_device"]["fridge_01"] == groceries["total"]
        assert groceries["by_device"]["light_01"] == empty["total"]

        world = client.app.state.world
        world.set_fault(LIGHT, "command", "unchanged")
        assert wire.command(LIGHT, {"power": True})[1] == []
        world.set_fault(LIGHT, "command", "reject")
        assert wire.command(LIGHT, {"power": True})[0]["status"] == "REJECTED"
        missing, _ = wire.command("mqtt:missing", {"power": True})
        assert missing["status"] == "UNSUPPORTED"
        world.local_change(LIGHT, "resident", {"power": True})
        clock.advance()

        window = {"start": marker["at"], "end": to_time}
        explicit = client.get(counts_url, params=window, auth=AUTH).raise_for_status()
        assert explicit.json()["total"] == {"notices": 2, "other_commands": 1}
        for invalid, status in (
            ({"start": marker["at"]}, 400),
            ({"start": to_time, "end": marker["at"]}, 400),
            ({**window, "start": "2026-10-17T14:00:00"}, 422),
        ):
            assert client.get(counts_url, params=invalid, auth=AUTH).status_code == status

    with TestClient(operator_app(tmp_path)) as client:
        saved = client.get(counts_url, auth=AUTH).raise_for_status().json()
        assert saved["window"]["start"] == marker["at"]
        assert saved["recording_since"] == marker["at"]
        assert saved["total"] == {"notices": 2, "other_commands": 3}
        assert saved["by_device"]["light_01"] == {"notices": 0, "other_commands": 2}
        assert saved["unbound_targets"] == {
            "mqtt:missing": {"notices": 0, "other_commands": 1}
        }
        post(client, marker_url)
        assert client.get(counts_url, auth=AUTH).json()["total"] == empty["total"]


def test_named_operator_actions_keep_path_and_identity_private(
    tmp_path, monkeypatch, clock
):
    monkeypatch.setattr(
        "spira_simulator.api.World", lambda path, profile: World(path, profile, clock)
    )
    received = []
    app = operator_app(tmp_path, received_source=SourceStub(received))
    snapshot_url = "/operator/snapshot"
    actions = [
        ("엄마", "device_panel", 2700, "user", "match"),
        ("아빠", "other_app", 3200, "unknown", "person-reported-unknown"),
    ]
    with TestClient(app) as client:
        signals = []
        monkeypatch.setattr(
            app.state.protocol,
            "publish",
            lambda topic, payload, **kwargs: signals.append(json.loads(payload)),
        )
        assert client.get(snapshot_url).status_code == 401
        prior = Wire(app.state.world).read(LIGHT)
        for i, (name, path, kelvin, by, _) in enumerate(actions):
            clock.advance()
            color = {"kelvin": kelvin}
            post(
                client,
                "/operator/device",
                target=LIGHT,
                actor="resident",
                actor_name=name,
                action_path=path,
                values={"color": color},
            )
            signal = signals[-1]
            assert signal["local_operation"] is (path == "device_panel")
            assert signal["operation_id"] is None and public_value(signal)
            assert signal["values"]["color"] == color
            assert signal["revisions"]["color"] != prior["revisions"]["color"]
            received.append(
                {
                    "event_id": f"ev_named_{i}",
                    "household_id": "h_042",
                    "source": "light_01",
                    "type": signal["event_type"],
                    "at": signal["occurred_at"],
                    "payload": {
                        "by": by,
                        "property": "color",
                        "from": prior["values"]["color"],
                        "to": color,
                    },
                }
            )
            prior = signal

        truth = client.get("/operator/truth", auth=AUTH).json()
        assert [(f["actor"], f["actor_name"], f["action_path"]) for f in truth] == [
            ("resident", name, path) for name, path, _, _, _ in actions
        ]
        compared = client.get("/operator/judge", auth=AUTH).raise_for_status().json()
        assert [(r["truth"]["actor_name"], r["verdict"]) for r in compared["results"]] == [
            (name, verdict) for name, _, _, _, verdict in actions
        ]
        # A later Hub command does not erase the most recent operator action.
        Wire(app.state.world).command(LIGHT, {"power": False})

    with TestClient(operator_app(tmp_path)) as client:
        snapshot = client.get(snapshot_url, auth=AUTH).json()
        light = next(d for d in snapshot["devices"] if d["target"] == LIGHT)
        assert light["last_operator_action"] == {
            "actor": "resident",
            "actor_name": "아빠",
            "action_path": "other_app",
            "event_type": "light.changed",
            "occurred_at": truth[-1]["occurred_at"],
        }
        public = client.get("/sim/snapshot").json()
        assert all("last_operator_action" not in d for d in public["devices"])
        wire = Wire(client.app.state.world)
        for body in (public, wire.read(LIGHT), wire.request("discover")[0]):
            assert public_value(body)
            assert all(name not in str(body) for name, *_ in actions)


def test_raw_home_signals_and_wall_clock_sim_at18_local_evidence(tmp_path, monkeypatch):
    app = operator_app(tmp_path)
    with TestClient(app) as client:
        signals = []
        monkeypatch.setattr(
            app.state.protocol,
            "publish",
            lambda topic, payload, **kw: signals.append(json.loads(payload)),
        )
        start = datetime.now(UTC)
        for action in ("delivery", "guests_arrive", "event_end"):
            post(client, "/operator/home", action=action)
        end = datetime.now(UTC)
        assert [(signal["target"], signal["event_type"]) for signal in signals] == [
            ("mqtt:sim_camera", "camera.package_removed"),
            ("mqtt:sim_doorbell", "doorbell.pressed"),
            ("mqtt:sim_door_lock", "door_lock.opened"),
            ("mqtt:sim_presence", "presence.room_occupied"),
            ("mqtt:sim_presence", "presence.room_empty"),
        ]
        assert signals[0]["payload"] == {"removed_count": 1, "remaining_count": 0}
        assert len({signal["signal_id"] for signal in signals}) == len(signals)
        assert all(
            signal["schema"] == DEVICE_SCHEMA and signal["kind"] == "event_signal"
            for signal in signals
        )
        assert all(
            start <= datetime.fromisoformat(signal["occurred_at"]) <= end
            for signal in signals
        )
        assert public_value(signals)
        assert client.post("/operator/clock", json={}, auth=AUTH).status_code == 404
        assert len(client.get("/operator/truth", auth=AUTH).json()) == len(signals)


def test_sim_at10_read_only_faint_waiting_and_item_only_episode(tmp_path):
    source = SourceStub(fixture_json("ep_9031/plan.v1.json"))
    with TestClient(operator_app(tmp_path, plan_source=source)) as client:
        initial = client.get("/sim/snapshot").json()
        viewer = client.get("/sim/viewer")
        assert viewer.status_code == 200 and "<button" not in viewer.text
        assert 'class="planned"' in viewer.text
        css = client.get("/sim/assets/house/viewer.css").raise_for_status().text
        assert "border: 1px dashed var(--green-line)" in css
        active_view = ElementTree.fromstring(
            client.get("/sim/viewer?fragment=true").raise_for_status().text
        )
        assert active_view.find('.//div[@data-device="light_01"]').get("data-resting") is None
        assert active_view.find('.//div[@data-device="styler_01"]').get("data-resting") == ""
        assert (
            active_view.findtext('.//div[@data-device="light_01"]/article/p[@class="device-value"]')
            == "3000K"
        )
        for mode, label in (
            ("stale", "오래된 관찰값"),
            ("missing", "관찰값 누락"),
            ("unavailable", "관찰 불가"),
        ):
            post(client, "/operator/fault", target=LIGHT, fault="readback", mode=mode)
            marked = client.get("/sim/viewer").text
            assert f'data-observation="{mode}"' in marked and label in marked
        post(client, "/operator/fault", target=LIGHT, fault="readback", mode="current")
        original = client.get("/sim/overlay").json()
        assert any(row["device"] == "cleaner_01" for row in original["preparation"])
        source.body = fixture_json("ep_9031/pull.json")
        overlay = client.get("/sim/overlay").json()
        assert overlay["errors"] == []
        assert not any(row["device"] == "cleaner_01" for row in overlay["preparation"])
        assert {(row["device"], row["command"]) for row in overlay["preparation"]} >= {
            ("cooktop_01", "child_lock"),
            ("plug_kettle", "off"),
        }
        assert any(
            row["device"] == "light_01" and row["command"] == "color"
            and row["wait"] == "guest_arrived" and row["task_id"] == "t_mood#3"
            for row in overlay["preparation"]
        )
        source.body = fixture_json("ep_9150/plan.v1.json")
        grocery = client.get("/sim/overlay").json()
        assert grocery["errors"] == []
        assert grocery["preparation"] == []
        grocery_episode = fixture_json("ep_9150/episode.json")
        assert len(grocery["notices"]) == len(grocery_episode["item_tasks"]) == 2
        assert (
            [
                (row["device"], row["command"], row["wait"], row["target_value"])
                for row in grocery["notices"]
            ]
            == [("fridge_01", "show_notice", "package.brought_in", None)] * 2
        )
        grocery_page = client.get("/sim/viewer").text
        assert "예정된 집 준비 없음" in grocery_page
        assert all(task["text"] not in grocery_page for task in grocery_episode["item_tasks"])
        grocery_view = ElementTree.fromstring(
            client.get("/sim/viewer?fragment=true").raise_for_status().text
        )
        assert {
            marker.get("data-device")
            for marker in grocery_view.findall(".//div[@data-device]")
            if marker.findall('p[@class="planned"]')
        } == {"fridge_01"}
        assert all(
            marker.get("data-resting") == ""
            for marker in grocery_view.findall(".//div[@data-device]")
            if marker.get("data-device") != "fridge_01"
        )
        for path in ("/sim/snapshot", "/sim/viewer", "/sim/overlay"):
            assert client.post(path, json={}).status_code == 405
        after = client.get("/sim/snapshot").json()
        assert [(d["values"], d["revisions"]) for d in after["devices"]] == [
            (d["values"], d["revisions"]) for d in initial["devices"]
        ]
        assert after["world_revision"] == initial["world_revision"]


@pytest.mark.provisional
def test_sim_at16_mixed_stage_labels_virtual_assumption_provisional(tmp_path):
    profile = load_profile().model_dump(mode="json", by_alias=True)
    light = next(d for d in profile["devices"] if d["target"] == LIGHT)
    profile["devices"].extend(
        [
            {
                **light,
                "target": "tapo:light_02",
                "logical_id": "light_02",
                "label": "Tapo light",
                "substrate": "physical",
                "local_operation_reporting": False,
                "assumption": None,
            },
            {
                **light,
                "target": "matter:light_03",
                "logical_id": "light_03",
                "label": "Matter light",
                "local_operation_reporting": False,
                "assumption": None,
            },
        ]
    )
    app = operator_app(tmp_path, profile=Profile.model_validate(profile))
    with TestClient(app) as client:
        tiles = {d["target"]: d for d in client.get("/sim/snapshot").json()["devices"]}
        assert (
            tiles[LIGHT]["assumption"]
            == "Virtual light panel local-operation reporting"
        )
        assert tiles[LIGHT]["qualification"] == "virtual_only"
        assert tiles["tapo:light_02"]["substrate"] == "physical"
        assert tiles["tapo:light_02"]["qualification"] == "unqualified"
        assert not tiles["tapo:light_02"]["available"]
        assert tiles["matter:light_03"]["substrate"] == "virtual"
        view = ElementTree.fromstring(client.get("/sim/viewer?fragment=true").text)
        for device, exceptions in (
            ("light_01", []),
            ("light_02", ["실물 기기 · 미검증"]),
            ("light_03", []),
        ):
            heading = view.find(f'.//div[@data-device="{device}"]/article/h3')
            assert [mark.text for mark in heading.findall("small")] == exceptions
        operator = client.get("/operator", auth=AUTH).raise_for_status().text
        assert "light_01 · Virtual · Class A (panel reporting assumed)" in operator
        assert "light_02 · Physical (unqualified) · Class B" in operator
        assert "light_03 · Virtual · Class B" in operator
        for target in ("tapo:light_02", "matter:light_03"):
            assert tiles[target]["local_operation_reporting"] is False
            assert app.state.world.read(target)["local_operation"] is False
        (matter_change,) = app.state.world.local_change(
            "matter:light_03", "guest", {"power": True}
        )
        assert matter_change["local_operation"] is False
        assert (
            client.post(
                "/operator/device",
                auth=AUTH,
                json={
                    "target": "tapo:light_02",
                    "actor": "resident",
                    "values": {"power": True},
                },
            ).status_code
            == 400
        )


@pytest.mark.parametrize(
    "status", ["restored", "skipped_user_changed", "failed", "unknown", "not_needed"]
)
def test_restore_overlay_keeps_report_and_observation_separate(tmp_path, status):
    records = fixture_json("ep_9031/executions.json")
    mood = next(
        r for r in records if r["kind"] == "restore" and r["task_id"] == "t_mood#3"
    )
    light_report = next(item for item in mood["items"] if item["device"] == "light_01")
    light_report["status"] = status
    with TestClient(
        operator_app(tmp_path, execution_source=SourceStub(records))
    ) as client:
        overlay = client.get("/sim/overlay").json()
        assert overlay["errors"] == []
        restores = overlay["restores"]
        assert {item["device"]: item["status"] for item in restores} == {
            "light_01": status,
            "display_01": "restored",
            "cooktop_01": "restored",
            "plug_kettle": "restored",
        }
        light = next(item for item in restores if item["device"] == "light_01")
        assert (
            light["substrate"] == "physical" and light["qualification"] == "unqualified"
        )
        current = next(
            device
            for device in client.get("/sim/snapshot").json()["devices"]
            if device["target"] == LIGHT
        )
        assert current["substrate"] == "virtual" and current["values"]["color"] == {
            "kelvin": 3000
        }
        assert public_value(restores)


def test_protective_fallback_overlay_preserves_observed_state(tmp_path):
    plan = fixture_json("ep_9031/plan.v3.json")
    records = fixture_json("ep_9031/executions.json")
    safety_task = next(task for task in plan["tasks"] if task.get("protective"))
    safety_report = next(
        record
        for record in records
        if record["kind"] == "restore" and record["task_id"] == safety_task["task_id"]
    )
    safety_report["at"] = safety_task["end"]["or_time"]
    for item in safety_report["items"]:
        item["status"] = "withheld_end_not_observed"
    app = operator_app(
        tmp_path, plan_source=SourceStub(plan), execution_source=SourceStub(records)
    )
    with TestClient(app) as client:
        wire = Wire(app.state.world)
        protection = {
            "mqtt:cooktop_01": {"child_lock": True},
            PLUG: {"power": False},
        }
        before = {}
        for target, desired in protection.items():
            receipt, _ = wire.command(target, desired)
            assert receipt["status"] == "ACCEPTED"
            before[target] = wire.read(target)

        overlay = client.get("/sim/overlay").json()
        assert overlay["errors"] == [] and overlay["preparation"] == []
        assert {item["device"]: item["status"] for item in overlay["restores"]} == {
            "light_01": "skipped_user_changed",
            "display_01": "restored",
            "cooktop_01": "withheld_end_not_observed",
            "plug_kettle": "withheld_end_not_observed",
        }
        tiles = {
            tile["target"]: tile
            for tile in client.get("/sim/snapshot").json()["devices"]
        }
        for target, desired in protection.items():
            tile = tiles[target]
            assert all(tile["values"][key] == value for key, value in desired.items())
            assert tile["revisions"] == before[target]["revisions"]


def test_sim_at19_live_3d_households_and_household_content(tmp_path, monkeypatch, clock):
    birthday_payload = fixture_json("ep_9031/plan.v3.json")
    birthday = Plan.model_validate(birthday_payload)
    mood = next(task.actions for task in birthday.tasks if task.task_id == "t_mood#3")
    notice = next(
        action.value
        for task in birthday.tasks
        for action in task.actions
        if action.cmd == "show_notice"
    )
    other_home = "http://127.0.0.1:8731/sim/viewer"
    monkeypatch.setenv(
        "WORLD_PEER_VIEWERS", f"부모님 댁={other_home},잘못된 주소=javascript:alert(1)"
    )
    app = operator_app(tmp_path, plan_source=SourceStub(birthday_payload))
    with TestClient(app) as client:
        monkeypatch.setattr(app.state.world, "clock", clock)
        wire = Wire(app.state.world)
        for action in mood:
            wire.command(f"mqtt:{action.device}", {action.cmd: action.value})
        wire.command(OVEN, {"preset": {"temp_c": 170, "minutes": 20}})
        wire.command("mqtt:fridge_01", {"show_notice": notice})
        post(
            client,
            "/operator/device",
            target="mqtt:purifier_01",
            actor="resident",
            actor_name="엄마",
            values={"mode": "auto"},
        )
        post(
            client,
            "/operator/device",
            target=OVEN,
            actor="resident",
            actor_name="엄마",
            start=True,
        )
        for event in ("delivery", "guests_arrive"):
            post(client, "/operator/home", action=event)
        clock.advance(60)
        page = client.get("/sim/viewer").raise_for_status().text
        assert f'<a href="{other_home}">부모님 댁</a>' in page
        assert "javascript:" not in page and "<h1>지아네</h1>" in page
        assert "h_042" not in page
        assert "h_042" in client.get("/operator", auth=AUTH).raise_for_status().text
        assert "SPIRA가 설정했어요" in page and "아직 실행 전이에요" in page
        assert "패널 조작을 알려 준다고 가정해요" not in page
        view = ElementTree.fromstring(client.get("/sim/viewer?fragment=true").text)
        clock_text = view.find(".//time")
        assert clock_text.text == "토 14:01"
        assert clock_text.get("datetime") == "2026-10-17T14:01:00+09:00"
        rooms = {
            room.findtext("h2"): {
                tile.get("data-device") for tile in room.findall(".//div[@data-device]")
            }
            for room in view.findall(".//section[@data-room]")
        }
        assert rooms == {
            "거실": {"cleaner_01", "light_01", "display_01", "purifier_01"},
            "주방": {"cooktop_01", "oven_01", "fridge_01", "plug_kettle"},
            "현관": {"styler_01"},
        }
        for device, content in {
            "oven_01": "170° · 19분 남음 · 굽는 중",
            "light_01": "분홍 330/45/70",
            "display_01": "공주 화면",
        }.items():
            assert (
                view.findtext(
                    f'.//div[@data-device="{device}"]/article/p[@class="device-value"]'
                )
                == content
            )
        for device, content in (("purifier_01", "자동"), ("styler_01", "대기 설정 없음")):
            marker = view.find(f'.//div[@data-device="{device}"]')
            assert marker.get("data-resting") == ""
            assert marker.find("article/h3").get("title") == content
            assert marker.find("article/h3/small") is None
            assert marker.findtext('article/p[@class="device-value visually-hidden"]') == content
        fridge = view.find('.//div[@data-device="fridge_01"]/article')
        notice_trigger = fridge.find('p[@class="device-value"]/button')
        assert notice_trigger.get("title") == notice_trigger.findtext("span") == notice
        detail = fridge.find(f'p[@id="{notice_trigger.get("popovertarget")}"]')
        assert detail.get("popover") == "auto" and detail.text == notice
        assert view.findtext('.//h3[@id="entrance-summary"]') == "손님 있음 · 이전 3건"
        assert view.find('.//h3[@id="entrance-summary"]').get("tabindex") == "0"
        assert [
            (row.get("data-signal"), row.text.strip())
            for row in view.findall('.//ul[@id="entrance-history"]/li')
        ] == [
            ("presence", "손님 있음"),
            ("door", "문 열림 감지"),
            ("bell", "초인종 울림"),
            ("package", "택배 들임"),
        ]
        post(
            client,
            "/operator/device",
            target=LIGHT,
            actor="resident",
            actor_name="아빠",
            values={"color": {"kelvin": 2700}},
        )
        post(client, "/operator/home", action="event_end")
        view = ElementTree.fromstring(client.get("/sim/viewer?fragment=true").text)
        person_marker = view.find('.//div[@data-device="light_01"]')
        assert person_marker.get("data-resting") is None
        assert person_marker.findtext('article/p[@class="device-value"]') == "2700K"
        assert person_marker.findtext('article/p[@class="change-marker"]') == "아빠 · 기기 패널"
        assert view.findtext('.//h3[@id="entrance-summary"]') == "손님 나감 · 이전 4건"
        post(client, "/operator/home", action="guests_arrive")
        view = ElementTree.fromstring(client.get("/sim/viewer?fragment=true").text)
        assert view.findtext('.//h3[@id="entrance-summary"]') == "손님 있음 · 이전 7건"
        history = view.findall('.//ul[@id="entrance-history"]/li')
        assert len(history) == 8
        assert sum(row.text.strip() == "손님 있음" for row in history) == 2

    first_home = "http://127.0.0.1:8730/sim/viewer"
    monkeypatch.setenv("WORLD_PEER_VIEWERS", f"지아네={first_home}")
    profile = load_profile(DEFAULT_PROFILE.with_name("ep_9120.json"))
    with TestClient(operator_app(tmp_path / "family", profile=profile)) as client:
        wire = Wire(client.app.state.world)
        wire.command("mqtt:speaker_01", {"play": {"playlist": "calm", "volume": 30}})
        page = client.get("/sim/viewer").text
        assert (
            f'<a href="{first_home}">지아네</a>' in page
            and "<h1>부모님 댁</h1>" in page
        )
        view = ElementTree.fromstring(client.get("/sim/viewer?fragment=true").text)
        assert {
            room.get("data-room"): {
                tile.get("data-device") for tile in room.findall(".//div[@data-device]")
            }
            for room in view.findall(".//section[@data-room]")
        } == {
            "living_room": {"cleaner_01", "speaker_01"},
            "kitchen": {"oven_01", "fridge_01"},
            "entrance": set(),
        }
        assert (
            view.findtext(
                './/div[@data-device="speaker_01"]/article/p[@class="device-value"]'
            )
            == "잔잔한 음악 · 볼륨 30"
        )
        assert view.findtext('.//section[@data-room="entrance"]/h2') == "현관"


def test_sim_at20_viewer_projects_world_markers_and_no_reasoning(tmp_path, monkeypatch):
    plan = fixture_json("ep_9031/plan.v3.json")
    card = fixture_json("ep_9031/card.v1.json")
    rationale = fixture_json("ep_9031/rationale.json")
    episode = fixture_json("ep_9031/episode.json")
    notices = [task["text"] for task in episode["item_tasks"]]
    hub = {
        "task_stories": [],
        "restoration": [],
        "events": fixture_json("ep_9031/events.json"),
        "episode": episode,
        "card": card,
        "rationale": rationale,
        "judge": {"verdict": "person-reported-unknown"},
    }
    monkeypatch.setenv("WORLD_HUB_STATE_URL", "http://hub.invalid/state")
    mock_http_source(monkeypatch, lambda request: httpx.Response(200, json=hub))
    app = operator_app(tmp_path, plan_source=SourceStub(plan))
    with TestClient(app) as client:
        Wire(app.state.world).command(
            "mqtt:display_01", {"play_mood": {"scene": "kids_party"}}
        )
        post(
            client,
            "/operator/device",
            target=LIGHT,
            actor="resident",
            actor_name="아빠",
            action_path="other_app",
            values={"color": {"kelvin": 2700}},
        )
        post(
            client,
            "/operator/device",
            target=PLUG,
            actor="external_automation",
            values={"power": False},
        )
        page = client.get("/sim/viewer").raise_for_status().text
        fragment = client.get("/sim/viewer?fragment=true").raise_for_status().text
        overlay = client.get("/sim/overlay").raise_for_status().json()
        public = client.get("/sim/snapshot").raise_for_status().json()
        assert public_value(overlay) and public_value(public)
        assert "아빠" not in json.dumps(public, ensure_ascii=False)
        assert overlay["errors"] == []
        for row in overlay["preparation"] + overlay["notices"]:
            assert set(row) == {
                "plan_id", "task_id", "device", "command", "target_value", "wait", "protective",
            }
        assert "오븐 · 굽기 설정 대기 170° 20분" in page
        assert '<span class="planned-clock"> · 토 14:00</span>' in page
        assert "냉장고 · 안내 표시 · 택배를 들이면" in page
        view = ElementTree.fromstring(fragment)
        oven_plan = view.find('.//div[@data-device="oven_01"]/p[@class="planned"]')
        assert "".join(oven_plan.itertext()) == "오븐 · 굽기 설정 대기 170° 20분 · 토 14:00"
        assert oven_plan.findtext('span[@class="planned-clock"]') == " · 토 14:00"
        visual_values = {
            marker.get("data-device"): json.loads(marker.get("data-values"))
            for marker in view.findall(".//div[@data-device]")
        }
        assert visual_values["display_01"] == {"play_mood": {"scene": "kids_party"}}
        assert visual_values["light_01"] == {"power": True, "color": {"kelvin": 2700}}
        assert visual_values["fridge_01"] == {"show_notice": None}
        for device, kind, expected in (
            ("light_01", "person", "아빠 · 가전 앱"),
            ("display_01", "spira", None),
            ("plug_kettle", "unknown", "누가 바꿨는지 모름"),
        ):
            tile = view.find(f'.//div[@data-device="{device}"]/article')
            assert tile.get("data-change") == kind
            assert tile.findtext('p[@class="change-marker"]') == expected
            assert (tile.find('h3/span[@class="spira-dot"]') is not None) == (kind == "spira")
        forbidden = [
            *notices,
            *[item["name"] for item in episode["items"]],
            card["text"],
            *[line["text"] for line in card["lines"]],
            card["intent_id"],
            rationale["intents"][0]["intent_text"],
            "person-reported-unknown",
            '"verdict"',
            '"by"',
            '"items"',
            '"intent_id"',
            '"actor"',
            '"actor_name"',
            '"action_path"',
            '"rationale"',
            '"card_id"',
            "marker-trace",
            "←",
        ]
        for surface in (
            page,
            fragment,
            json.dumps(visual_values, ensure_ascii=False),
            json.dumps(overlay, ensure_ascii=False),
            json.dumps(public, ensure_ascii=False),
        ):
            assert all(value not in surface for value in forbidden)


class SurfaceForms(HTMLParser):
    """Read the actual button payload and destination from server-rendered forms."""

    def __init__(self, page):
        super().__init__()
        self.form = {}
        self.person = None
        self.buttons = []
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.form = attrs
        elif tag == "input" and attrs.get("name") == "person":
            self.person = attrs["value"]
        elif tag == "option" and "selected" in attrs:
            self.person = attrs["value"]
        elif tag == "button" and attrs.get("name") == "control":
            url = attrs.get("formaction") or self.form["action"]
            self.buttons.append(
                (url, {"person": self.person, "control": attrs["value"]})
            )


@pytest.mark.provisional
def test_sim_at21_named_panel_and_appliance_app_share_device_path(
    tmp_path, monkeypatch
):
    app = operator_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/app").status_code == 401
        assert client.get("/operator").status_code == 401
        panel = client.get("/operator", auth=AUTH).raise_for_status().text
        appliance = client.get("/app", auth=AUTH).raise_for_status().text
        for page in (panel, appliance):
            assert 'href="/sim/assets/house/tokens.css"' in page
            assert 'href="/sim/style.css"' in page
        assert "엄마 · 기기 패널 · 조명 2700K로 변경" in panel
        assert all(
            f"<summary>{name}</summary>" in panel
            for name in ("엄마", "아빠", "지아", "손님")
        )
        assert "Apply property values" in panel and "Open appliance app" in panel
        assert "가전 앱 · 지아네" in appliance and "3000K" in appliance
        assert "굽기 시작" in appliance and "굽기 중지" not in appliance
        assert "공주 화면 켜기" in appliance
        panel_url, panel_fields = next(
            (url, fields)
            for url, fields in SurfaceForms(panel).buttons
            if fields == {"person": "엄마", "control": "kelvin_2700"}
        )
        app_url, app_fields = next(
            (url, fields)
            for url, fields in SurfaceForms(appliance).buttons
            if fields["control"] == "kelvin_4000"
        )
        assert app_fields["person"] == "아빠"
        assert client.post(app_url, data=app_fields).status_code == 401
        assert client.post(panel_url, data=panel_fields).status_code == 401
        cross_origin = client.post(
            app_url,
            data=app_fields,
            auth=AUTH,
            headers={"Origin": "http://elsewhere.invalid"},
        )
        assert cross_origin.status_code == 403
        signals = []
        monkeypatch.setattr(
            app.state.protocol,
            "publish",
            lambda topic, payload, **kw: signals.append(json.loads(payload)),
        )
        for url, fields, flag in (
            (panel_url, panel_fields, True),
            (app_url, app_fields, False),
        ):
            response = client.post(
                url, data=fields, auth=AUTH, follow_redirects=False,
                headers={"Origin": str(client.base_url).rstrip("/")},
            )
            assert response.status_code == 303
            assert signals[-1]["local_operation"] is flag
            assert signals[-1]["operation_id"] is None
            assert signals[-1]["target"] == LIGHT
        current = client.get(response.headers["location"], auth=AUTH).text
        assert "4000K" in current and '<option value="아빠" selected>' in current
        truth = client.get("/operator/truth", auth=AUTH).json()
        assert [
            (row["actor"], row["actor_name"], row["action_path"]) for row in truth
        ] == [
            ("resident", "엄마", "device_panel"),
            ("resident", "아빠", "other_app"),
        ]
        assert public_value(signals)
