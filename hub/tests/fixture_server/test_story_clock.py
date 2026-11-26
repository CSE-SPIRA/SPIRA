from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from . import create_app
from .moments import QUIET_END
from .story_clock import StoryClock, story_now
from .test_fixture_server import HEADERS
from .test_scene_support import CLOCK, SELECT, upload

MOMENTS = "/v1/demo/moments"


def test_wall_clock_and_ramp_return_to_normal_speed():
    real = datetime.fromisoformat("2026-11-24T12:00:00+09:00")
    story = datetime.fromisoformat("2026-10-15T21:00:08+09:00")
    clock = StoryClock(real)
    assert story_now(clock.state, real + timedelta(seconds=2)) == real + timedelta(seconds=2)
    clock.set(story, real)
    assert story_now(clock.state, real + timedelta(seconds=2)) == story + timedelta(seconds=2)
    clock.advance(story + timedelta(hours=1), real, 6)
    assert story_now(clock.state, real + timedelta(seconds=3)) == story + timedelta(minutes=30)
    assert story_now(clock.state, real + timedelta(seconds=6)) == story + timedelta(hours=1)
    assert story_now(clock.state, real + timedelta(seconds=7)) == story + timedelta(hours=1, seconds=1)


def test_clock_validation_and_forward_only_advance():
    client = TestClient(create_app(scene_controls=True))
    current = client.get(CLOCK).json()
    assert current["real_at"] == current["story_at"]
    assert current["now"].endswith("+09:00")
    earlier = "2026-10-15T12:00:00+09:00"
    assert client.post(CLOCK, json={"advance_to": earlier}).status_code == 409
    assert client.post(CLOCK, json={"advance_to": earlier, "set_to": earlier}).status_code == 422
    assert client.post(CLOCK, json={"set_to": earlier[:-6]}).status_code == 422
    for seconds in (0, 61, "6", True):
        assert client.post(CLOCK, json={"advance_to": earlier, "over_seconds": seconds}).status_code == 422
    assert client.get(CLOCK).json()["version"] == current["version"]
    jumped = client.post(CLOCK, json={"set_to": earlier}).json()
    assert jumped["version"] == current["version"] + 1
    assert jumped["story_at"] == jumped["now"] == earlier
    assert jumped["rate"] == 1
    assert jumped["ramp_until"] is None

    target = "2026-10-15T12:00:00.500000+09:00"
    advanced = client.post(CLOCK, json={"advance_to": target, "over_seconds": 60}).json()
    assert 0 < advanced["rate"] < 1
    assert advanced["version"] == jumped["version"] + 1


def test_next_uses_recorded_events_and_time_preroll():
    client = TestClient(create_app(scene_controls=True, demo_mode=True), headers=HEADERS)
    assert client.get(MOMENTS).json() == []
    assert client.post(CLOCK + "/next").status_code == 404
    assert client.post(SELECT, json={"episode_id": "ep_9031"}).status_code == 202
    assert upload(client, "birthday").status_code == 202
    assert client.get(CLOCK).json()["story_at"] == "2026-10-15T21:00:08+09:00"
    moments = client.get(MOMENTS).json()
    assert [(entry["kind"], entry["at"], entry["event"]) for entry in moments] == [
        ("time", "2026-10-15T21:00:12+09:00", QUIET_END),
        ("event", "2026-10-16T18:05:10+09:00", "package.brought_in"),
        ("time", "2026-10-17T12:30:00+09:00", None),
        ("time", "2026-10-17T13:30:00+09:00", None),
        ("event", "2026-10-17T13:52:31+09:00", "guest_arrived"),
        ("time", "2026-10-17T14:00:00+09:00", None),
        ("event", "2026-10-17T15:10:05+09:00", "light.changed"),
        ("event", "2026-10-17T17:50:00+09:00", "event_end"),
    ]
    assert moments[3]["task_ids"] == ["t_safe#2", "t_mood#3"]
    assert len({moment["id"] for moment in moments}) == len(moments)
    assert client.post(CLOCK + "/next", json={"over_seconds": 61}).status_code == 422

    for index, moment in enumerate(moments):
        at = datetime.fromisoformat(moment["at"])
        options = {"json": {"over_seconds": 2}} if index else {}
        assert client.post(CLOCK + "/next", **options).json() == moment
        state = client.get(CLOCK).json()
        real, ramp, story = (datetime.fromisoformat(state[key]) for key in ("real_at", "ramp_until", "story_at"))
        assert ramp - real == timedelta(seconds=2 if index else 6)
        lead = timedelta(seconds=20 if moment["kind"] == "time" and moment["event"] != QUIET_END else 0)
        assert story + (ramp - real) * state["rate"] == at - lead
        if lead:
            assert client.post(CLOCK, json={"set_to": (at - lead).isoformat()}).status_code == 200
            assert client.post(CLOCK + "/next").status_code == 409
        assert client.post(CLOCK, json={"set_to": at.isoformat()}).status_code == 200

    assert client.post(CLOCK + "/next").status_code == 404
