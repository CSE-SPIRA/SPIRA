"""Drive the running Hub through the fixture's armed HTTP cases."""

from contextlib import asynccontextmanager
from datetime import datetime

import httpx2 as httpx
import pytest
from spira_contracts.validate import validate

from hub.tests.fixture_server import create_app
from hub.tests.fixture_server.api import CONTROL
from hub.tests.fixture_server.catalogue import DERIVED_FIELDS
from hub.tests.fixture_server.scene_support import NextOrder

from .peers import Clock, Scenario, fixture
from .test_acceptance import install_birthday, run

EPISODE = "ep_9031"
CARDS = "/v1/households/h_042/cards"
PLANS = "/v1/hub/plans?household=h_042"


async def post(client, path, **json):
    reply = await client.post(path, json=json)
    assert reply.status_code == 200, reply.text
    return reply.json()


@asynccontextmanager
async def rehearsal(tmp_path, case=None):
    app = create_app(EPISODE, scene_controls=True, default_scene=NextOrder(episode_id=EPISODE))
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
    async with httpx.AsyncClient(base_url="http://127.0.0.1", transport=transport) as control:
        if case:
            await post(control, CONTROL + "/case", id=case)
        await post(control, CONTROL + "/episode", action="share")
        await post(control, CONTROL + "/judgment", preset="release", scope="current")
        clock = Clock("2026-10-17T12:25:00+09:00")
        hub = Scenario(tmp_path, clock, episode=EPISODE, transport=transport)
        install_birthday(hub)
        hub.boot()
        try:
            await hub.reconcile()
            yield control, hub, clock
        finally:
            await hub.close()


@pytest.mark.parametrize("case", ["equal-plan", "lower-plan"])
def test_control_ignores_replayed_version(tmp_path, case):
    async def exercise():
        async with rehearsal(tmp_path) as (control, hub, _):
            card = (await hub.http.get(CARDS)).json()["cards"][0]
            reaction = await post(hub.http, f"/v1/cards/{card['card_id']}/reactions",
                                  reaction="line_off", task_id="t_clean#1")
            validate(reaction, "card.json")
            assert await hub.runtime.refresh()
            await hub.runtime.flush()
            task = hub.store.task(EPISODE, "t_clean#1")
            assert task["cancel"] is False and not task["active"]
            before = await post(control, CONTROL + "/case", id=case)
            assert await hub.runtime.refresh()
            await hub.runtime.flush()
            after = (await control.get(CONTROL + "/state")).json()
            old, new = after["plans"]
            expected = 0 if case == "lower-plan" else 1
            assert [plan["count"] - prior["count"] for plan, prior in zip(
                after["plans"], before["plans"], strict=True,
            )] == [int(index == expected) for index in range(2)]
            assert old["acked_at"] == before["plans"][0]["acked_at"]
            assert new["acked_at"] == before["plans"][1]["acked_at"]
            assert hub.store.floor(EPISODE) == 2
            assert hub.store.task(EPISODE, "t_clean#1") == task
            assert hub.world.commands == []

    run(exercise)


@pytest.mark.parametrize("case,reason", [
    ("ack-device", "unknown_device"), ("ack-command", "unsupported_cmd"), ("ack-value", "value_out_of_range"),
], ids=["ack-device", "ack-command", "ack-value"])
def test_control_ack_rejection(tmp_path, case, reason):
    async def exercise():
        async with rehearsal(tmp_path, case) as (control, hub, _):
            response = await hub.http.get(PLANS)
            assert response.status_code == 200
            pull = response.json()
            validate(pull, "plan_pull.json")
            altered, = pull["plans"]
            expected = fixture("plan.v1.json")
            expected["sent_at"] = altered["sent_at"]  # Normal live replay retimes publication.
            target = next(task for task in expected["tasks"] if task["task_id"] == "t_oven#4")["actions"][0]
            field, value = DERIVED_FIELDS[case]
            if field.endswith(".temp_c"):
                target["value"]["temp_c"] = value
            else:
                target[field.split(".")[-1]] = value
            assert altered == expected
            state = (await control.get(CONTROL + "/state")).json()
            plan, = state["plans"]
            validate(plan["ack"], "ack.json")
            assert plan["ack"] == {
                "plan_version": 1, "status": "admitted",
                "rejected_tasks": [{"task_id": "t_oven#4", "reason": reason}],
            }
            assert hub.store.task(EPISODE, "t_oven#4") is None
            assert hub.store.task(EPISODE, "t_clean#1")["active"]
            cards = (await hub.http.get(CARDS)).json()
            validate(cards, "cards_response.json")
            assert next(line for line in cards["cards"][0]["lines"] if line["task_id"] == "t_oven#4")["state"] == "failed"
            assert hub.world.commands == []
            at = next(task["end"]["or_time"] for task in altered["tasks"] if task["task_id"] == "t_safe#2")
            await post(control, CONTROL + "/clock", action="set", at=at)
            rationale = await hub.http.get(f"/v1/episodes/{EPISODE}/rationale")
            assert rationale.status_code == 200
            validate(rationale.json(), "rationale.json")
            assert rationale.json()["observations"]  # Closing the window uses the recorded action.
            assert len((await control.get(CONTROL + "/state")).json()["plans"]) == 1

    run(exercise)


def test_control_preflight_failure(tmp_path):
    async def exercise():
        async with rehearsal(tmp_path) as (control, hub, clock):
            task = hub.store.task(EPISODE, "t_clean#1")
            clock.now = datetime.fromisoformat(task["body"]["trigger"]["time"])
            await post(control, CONTROL + "/clock", action="set", at=clock().isoformat())

            async def arm_on_device_read(_):
                hub.world.before_read = None
                state = await post(control, CONTROL + "/case", id="preflight")
                assert state["faults"][0]["route"] == "plans"

            hub.world.before_read = arm_on_device_read
            await hub.cycle()
            executions = (await hub.receipts())["executions"]
            result, = executions
            validate(result, "execution_result.json")
            assert (result["status"], result["reason"], result["task_id"]) == ("blocked", "plan_unconfirmed", "t_clean#1")
            assert hub.world.commands == []
            state = (await control.get(CONTROL + "/state")).json()
            assert state["last"]["hub_pull"]["status"] == 503
            assert state["faults"][0]["count"] is None
            assert not (await post(control, CONTROL + "/fault/hub/clear"))["faults"]
            cards = (await hub.http.get(CARDS)).json()
            validate(cards, "cards_response.json")
            assert cards["cards"][0]["lines"][0]["state"] == "blocked"

    run(exercise)


def test_control_retries_hub_outbox_after_apply_then_fail(tmp_path):
    async def exercise():
        async with rehearsal(tmp_path) as (control, hub, _):
            await post(control, CONTROL + "/case", id="event-resend")
            hub.world.signal("camera.package_removed", "mqtt:sim_camera", removed_count=1, remaining_count=0)
            await hub.runtime.flush()
            sent, = (await hub.receipts())["events"]
            pending, = hub.store.pending("event")
            assert pending["error"] == "HTTP 503"
            assert hub.store.floor(EPISODE) == 1
            assert len((await control.get(CONTROL + "/state")).json()["plans"]) == 2
            await hub.runtime.flush()
            assert (await hub.receipts())["events"] == [sent, sent]
            assert not hub.store.pending("event")
            assert hub.store.floor(EPISODE) == 1  # The retry reports plans_changed: false.
            assert await hub.runtime.refresh()
            assert hub.store.floor(EPISODE) == 2
            await post(control, CONTROL + "/case", id="result-resend")
            await hub.cycle()
            first, = (await hub.receipts())["executions"]
            assert hub.store.pending("execution")[0]["error"] == "HTTP 503"
            commands = len(hub.world.commands)
            await hub.runtime.flush()
            assert not hub.store.pending("execution")
            assert (await hub.receipts())["executions"][:2] == [first, first]
            assert len(hub.world.commands) == commands == 2

    run(exercise)
