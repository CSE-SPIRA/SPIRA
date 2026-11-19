import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from conftest import LIGHT, OVEN, PLUG, Wire, fixture_json
from fastapi.testclient import TestClient
from spira_contracts.plan import Plan
from spira_simulator.api import create_app
from spira_simulator.profile import Profile, load_profile, public_value
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
    assert len(overlay["item_notices"]) == 2
    assert {
        (row["device"], row["status"], row["substrate"]) for row in overlay["restores"]
    } == {
        ("cooktop_01", "restored", "virtual"),
        ("plug_kettle", "restored", "virtual"),
        ("light_01", "skipped_user_changed", "virtual"),
        ("display_01", "restored", "virtual"),
    }


def test_judge_reads_events_from_multiple_fixture_receipt_batches(
    tmp_path, monkeypatch, captured_receipts
):
    monkeypatch.setenv("WORLD_RECEIVED_URL", "http://fixture.invalid/_fixture/receipts")

    def handle(request):
        assert request.method == "GET"
        assert request.url.path == "/_fixture/receipts"
        return httpx.Response(200, json=captured_receipts)

    mock_http_source(monkeypatch, handle)
    light, oven = [
        event
        for batch in captured_receipts["events"]
        for event in batch
        if event["payload"].get("by") == "user"
    ]
    app = operator_app(tmp_path)
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
        result = client.get("/operator/judge", auth=AUTH).raise_for_status().json()

    comparisons = [
        (row["event_id"], row["by"], row["verdict"]) for row in result["results"]
    ]
    assert comparisons == [
        (light["event_id"], "user", "match"),
        (oven["event_id"], "user", "match"),
    ]


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
        script = client.get("/sim/stage.js").text
        assert "Stale" in script and "Readback missing" in script
        assert "border: 1px dashed #88998e" in client.get("/sim/style.css").text
        original = client.get("/sim/overlay").json()
        assert any(row["task_id"] == "t_clean#1" for row in original["preparation"])
        source.body = fixture_json("ep_9031/pull.json")
        overlay = client.get("/sim/overlay").json()
        assert overlay["errors"] == []
        assert not any(row["task_id"] == "t_clean#1" for row in overlay["preparation"])
        protective_devices = {
            row["device"] for row in overlay["preparation"] if row["protective"]
        }
        assert protective_devices == {"cooktop_01", "plug_kettle"}
        assert any(
            row["device"] == "light_01" and row["wait"] == "guest_arrived"
            for row in overlay["preparation"]
        )
        assert not any(
            row["device"] == "light_01" and row["target_value"] == {"kelvin": 3000}
            for row in overlay["preparation"]
        )
        source.body = fixture_json("ep_9150/plan.v1.json")
        grocery = client.get("/sim/overlay").json()
        assert grocery["errors"] == []
        assert grocery["preparation"] == []
        grocery_episode = fixture_json("ep_9150/episode.json")
        assert {
            row["task_id"]: row["target_value"] for row in grocery["item_notices"]
        } == {task["task_id"]: task["text"] for task in grocery_episode["item_tasks"]}
        assert len(grocery["item_notices"]) == len(grocery_episode["item_tasks"]) == 2
        assert all(
            row["device"] == "fridge_01"
            and row["command"] == "show_notice"
            and row["wait"] == "package.brought_in"
            and not row["protective"]
            for row in grocery["item_notices"]
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
