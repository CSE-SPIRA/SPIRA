import asyncio
from datetime import timedelta
from types import SimpleNamespace

import httpx2 as httpx
import pytest

from hub.spira_hub.__main__ import DemoClock
from hub.spira_hub.story_clock import ClockState, story_now

from .peers import Clock, Scenario, Stub, action, task
from .test_acceptance import guest, install_birthday


def test_story_clock_polls_and_keeps_running_after_a_failed_poll(monkeypatch):
    async def exercise():
        real = Clock()
        monkeypatch.setattr("hub.spira_hub.__main__.wall_time", real)
        start = real()
        story = start - timedelta(days=30)
        state = ClockState(version=3, real_at=start, story_at=story, rate=10,
                           ramp_until=start + timedelta(seconds=6))
        responses = iter([httpx.Response(200, json={**state.model_dump(mode="json"), "now": story.isoformat()}),
                          httpx.Response(503), httpx.Response(200, json={})])
        published = []

        async def publish(value):
            published.append(value)

        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(responses))) as client:
            clock = DemoClock("http://fixture/v1/demo/clock", client, SimpleNamespace(publish_clock=publish))
            assert clock.now() == start
            await clock.poll()
            real.advance(seconds=3)
            assert clock.now() == story + timedelta(seconds=30)
            await clock.poll()
            real.advance(seconds=3)
            assert clock.now() == story + timedelta(seconds=60)
            await clock.poll()
            real.advance(seconds=2)
            assert clock.now() == story + timedelta(seconds=62)
            assert published == [state, state, state]
    asyncio.run(exercise())


@pytest.mark.parametrize("arrival_in_window", [True, False])
def test_runtime_dispatches_once_through_ramp_and_honors_story_guest_window(tmp_path, arrival_in_window):
    async def exercise():
        real = Clock("2026-11-24T10:00:00+09:00")
        story = Clock("2026-10-17T12:29:00+09:00")()
        state = ClockState(version=2, real_at=real(), story_at=story, rate=20,
                           ramp_until=real() + timedelta(seconds=10))

        def now():
            return story_now(state, real())

        due = (story + timedelta(seconds=50)).isoformat()
        opens = (story + timedelta(seconds=90)).isoformat()
        closes = (story + timedelta(seconds=235)).isoformat()
        timed = task(now, trigger={"time": due})
        mood = task(now, action("light_01", "color_temp", {"kelvin": 2700}), n=2, trigger={
            "event": "guest_arrived", "first_only": True, "window": {"from": opens, "to": closes},
        })
        hub = Scenario(tmp_path, now, stub=Stub(now, timed, mood))
        install_birthday(hub)
        hub.boot()
        await hub.reconcile()

        guest(hub.world, real)
        await hub.cycle()
        assert len(hub.world.commands) == 0

        real.advance(seconds=1)
        await hub.cycle()
        assert len(hub.world.commands) == 1

        if arrival_in_window:
            real.advance(seconds=2)
        else:
            real.advance(seconds=46)
            state_json = (await hub.dashboard.get("/state")).json()
            row = next(row for row in state_json["waiting"] if row["task_id"] == "t_test#2")
            assert row["status"] == "window_passed"
        guest(hub.world, real)
        await hub.cycle()
        assert len(hub.world.commands) == (2 if arrival_in_window else 1)

        real.advance(minutes=1)
        await hub.cycle()
        assert len(hub.world.commands) == (2 if arrival_in_window else 1)
        await hub.close()
    asyncio.run(exercise())
