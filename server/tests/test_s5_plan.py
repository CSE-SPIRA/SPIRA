"""S5 plan confirmation and cards (spec §11): T17 T22 T23 T24 T34(held) T35 T40 T44 T49 T51 T58 T59 T64."""

import copy
from datetime import timedelta

from spira_contracts.validate import validate
from sqlalchemy import select

from spira_server import clock
from spira_server.db.engine import session_scope
from spira_server.db.models import Card, CardLine, CareNoticeShown, Episode, Plan, Task, Window
from spira_server.pipeline import runner, s5_plan
from spira_server.pipeline.s4_tasks import Draft, S4Result
from spira_server.pipeline.s5_cards import ActionResult, LineInput, card_body, end_state, line_state

from . import s5_helpers as h
from .factories import fixture
from .s4_helpers import JUDGED, ep9031, output


def _plan(ep: str, version: int = 1) -> dict:
    with session_scope() as s:
        return s.get(Plan, (ep, version)).body


def _cards(ep: str, now) -> list[dict]:
    with session_scope() as s:
        return [card_body(s, c, now) for c in s.execute(select(Card).where(Card.episode_id == ep)).scalars()]


def _status(ep: str) -> str:
    with session_scope() as s:
        return s.get(Episode, ep).status


def test_t17_t22_t64_ep9031(mock_llm):
    ep = ep9031()
    h.restart_card_ids(331)
    s4 = h.s4_for(mock_llm, ep, output(), JUDGED)
    out = s5_plan.finalize(ep, s4, now=JUDGED)
    assert (out.published, out.card_ids, out.dropped, out.status) == (1, ["nc_331"], {}, "notified")
    plan = _plan(ep)
    assert plan == fixture("ep_9031/plan.v1.json")                             # T17 (incl. protective, T64)
    assert [t.get("protective") for t in plan["tasks"]][:3] == [None, True, None]
    [card] = _cards(ep, JUDGED)
    assert card == fixture("ep_9031/card.v1.json")                             # T22
    validate(plan, "plan.json")                                                 # T40
    validate(card, "card.json")
    with session_scope() as s:
        w = s.execute(select(Window)).scalar_one()
        assert (w.status, w.memory, clock.iso(w.scheduled_start), clock.iso(w.end_due)) == (
            "pending", "pending", "2026-10-17T14:00:00+09:00", "2026-10-17T20:00:00+09:00")
        e = s.get(Episode, ep)
        assert (e.judged, e.stage, e.plan_version, e.next_task_n, e.next_card_ordinal) == (True, "done", 1, 7, 2)
        assert {t.task_id: t.status for t in s.execute(select(Task)).scalars()} == {
            f"t_{n}": "live" for n in ("clean#1", "safe#2", "mood#3", "oven#4", "fridge#5", "fridge#6")}


def test_t34_ep9120_held_card_and_plan(mock_llm):
    ep = h.ep9120()
    h.restart_card_ids(340)
    s4 = h.s4_for(mock_llm, ep, h.OUT_9120, h.JUDGED_9120)
    out = s5_plan.finalize(ep, s4, now=h.JUDGED_9120)
    assert out.status == "held" and out.dropped == {}
    assert _plan(ep) == fixture("ep_9120/plan.v1.json")                         # held lines are not sent
    [card] = _cards(ep, h.JUDGED_9120)
    assert card == fixture("ep_9120/card.held.json")
    validate(card, "card.json")


def test_t35_ep9150_groceries(mock_llm):
    ep = h.ep9150()
    s4 = h.s4_for(mock_llm, ep, h.OUT_9150, h.JUDGED_9150)
    out = s5_plan.finalize(ep, s4, now=h.JUDGED_9150)
    assert (out.status, out.card_ids) == ("judged", [])
    assert _plan(ep) == fixture("ep_9150/plan.v1.json")


def _draft(task_id, actions, trigger, end=None, way="run", source="situation", room=None, meta=None, bundle=0):
    return Draft(task_id=task_id, source=source, way=way, actions=actions, trigger=trigger,
                 end=end or {"on": "event_end", "or_time": "2026-10-17T20:00:00+09:00", "restore": True},
                 need="n", line=task_id, target_room=room, bundle=bundle if source == "situation" else None,
                 meta=meta or {})


def _finalize(ep, drafts, now=JUDGED, whens=None):
    from spira_server.pipeline.s4_time import When
    w = When(clock.parse("2026-10-17T14:00:00+09:00"), clock.parse("2026-10-17T17:00:00+09:00"), "calendar")
    s4 = S4Result(drafts=drafts, whens=whens if whens is not None else {0: w},
                  next_task_n=max([int(d.task_id.split("#")[1]) for d in drafts] + [0]) + 1)
    return s5_plan.finalize(ep, s4, now=now)


def test_t23_t59_t58_safety_net():
    ep = ep9031()
    t = {"time": "2026-10-17T13:30:00+09:00"}
    out = _finalize(ep, [
        _draft("t_night#1", [{"device": "cleaner_01", "cmd": "clean", "value": {"room": "거실"}}],
               {"time": "2026-10-16T23:10:00+09:00"}),                                       # noisy at 23:10
        _draft("t_room#2", [{"device": "light_01", "cmd": "color_temp", "value": {"kelvin": 3000}}], t, room="주방"),
        _draft("t_never#3", [{"device": "cooktop_01", "cmd": "off"}], t),                    # not delegated
        _draft("t_oven#4", [{"device": "oven_01", "cmd": "start"}], {"time": "2026-10-17T14:00:00+09:00"},
               end={"on": "oven.started", "by": "user", "restore": False}, way="standby"),   # T59
        _draft("t_range#5", [{"device": "light_01", "cmd": "color_temp", "value": {"kelvin": 9000}}], t),
        _draft("t_late#6", [{"device": "light_01", "cmd": "color_temp", "value": {"kelvin": 3000}}],
               {"time": "2026-10-15T20:50:00+09:00"}),                                       # T58: 21 min ago
        _draft("t_win#7", [{"device": "display_01", "cmd": "off"}],
               {"event": "guest_arrived", "first_only": True,
                "window": {"from": "2026-10-15T10:00:00+09:00", "to": "2026-10-15T12:00:00+09:00"}}),
        _draft("t_endb#8", [{"device": "display_01", "cmd": "off"}], {"time": "2026-10-17T15:00:00+09:00"},
               end={"time": "2026-10-17T15:00:00+09:00", "restore": True}),
        _draft("t_ok#9", [{"device": "light_01", "cmd": "color_temp", "value": {"kelvin": 3000}}], t, room="거실"),
    ])
    assert out.dropped == {"t_night#1": "quiet_hours", "t_room#2": "room_mismatch", "t_never#3": "not_delegated",
                           "t_oven#4": "unsafe_cmd", "t_range#5": "value_out_of_range", "t_late#6": "late",
                           "t_win#7": "late", "t_endb#8": "late"}
    assert [x["task_id"] for x in _plan(ep)["tasks"]] == ["t_ok#9"]
    with session_scope() as s:
        assert s.get(Task, (ep, "t_oven#4")).drop_reason == "unsafe_cmd"


def _notice(task_id, item, kind, intent_change=None):
    return _draft(task_id, [{"device": "fridge_01", "cmd": "show_notice", "value": f"{item} 안내"}],
                  {"event": "package.brought_in", "released": False},
                  end={"on": "fridge.door_opened", "after": "2h", "or_after": "12h", "restore": False},
                  way="notice", source="item", meta={"item": item, "kind": kind, "intent_change": intent_change})


def test_t24_fridge_notices():
    ep = ep9031()
    with session_scope() as s:
        s.add(CareNoticeShown(household_id="h_042", item_type="우유", kind="storage", count=2))
        s.add(CareNoticeShown(household_id="h_042", item_type="딸기", kind="storage", count=2))
    out = _finalize(ep, [_notice("t_fridge#1", "우유", "storage"), _notice("t_fridge#2", "바지락", "prep"),
                         _notice("t_fridge#3", "딸기", "storage", intent_change="토요일 직전에"),
                         _notice("t_fridge#4", "계란", "storage"), _notice("t_fridge#5", "두부", "storage")], whens={})
    assert out.dropped == {"t_fridge#1": "repeated_notice", "t_fridge#5": "notices_per_screen"}
    assert [x["task_id"] for x in _plan(ep)["tasks"]] == ["t_fridge#2", "t_fridge#3", "t_fridge#4"]


def test_t49_overlap_priorities():
    ep = ep9031()
    _finalize(ep, [_draft("t_mood#1", [{"device": "light_01", "cmd": "color_temp", "value": {"kelvin": 3000}}],
                          {"time": "2026-10-16T19:00:00+09:00"},
                          end={"on": "event_end", "or_time": "2026-10-16T22:00:00+09:00", "restore": True})])
    from .s4_helpers import episode
    episode("ep_9032", intent={"bundles": [], "unbundled": [], "none_reason": "x", "error": None})
    out = _finalize("ep_9032", [
        _draft("t_clean#1", [{"device": "light_01", "cmd": "color_temp", "value": {"kelvin": 4000}}],
               {"time": "2026-10-16T20:00:00+09:00"}),                       # new plan loses to the confirmed one
        _draft("t_glow#2", [{"device": "light_01", "cmd": "color", "value": {"hue": 1, "saturation": 1,
                                                                             "brightness": 1}}],
               {"event": "package.brought_in", "released": False},
               end={"on": "light.changed", "or_after": "2h", "restore": True}, source="item"),
    ], whens={})
    assert out.dropped == {"t_clean#1": "overlap"}
    assert out.cancelled_elsewhere == [("ep_9031", "t_mood#1")]             # per-item beats the confirmed plan
    v2 = _plan(ep, 2)
    assert v2["tasks"] == [] and v2["cancelled"] == [{"task_id": "t_mood#1", "restore": False}]
    assert [x["task_id"] for x in _plan("ep_9032")["tasks"]] == ["t_glow#2"]


def test_same_command_same_value_keeps_existing():
    ep = ep9031()
    a = [{"device": "fridge_01", "cmd": "show_notice", "value": "x"}]
    _finalize(ep, [_draft("t_a#1", [{"device": "display_01", "cmd": "off"}], {"time": "2026-10-16T19:00:00+09:00"})])
    from .s4_helpers import episode
    episode("ep_9033", intent={"bundles": [], "unbundled": [], "none_reason": "x", "error": None})
    out = _finalize("ep_9033", [_draft("t_b#1", [{"device": "display_01", "cmd": "off"}],
                                       {"time": "2026-10-16T18:00:00+09:00"}, source="item"),
                                _notice("t_n#2", "우유", "prep")], whens={})
    assert out.dropped == {"t_b#1": "overlap"} and a


def test_paused_household_nothing_live(mock_llm):
    ep = ep9031()
    s4 = h.s4_for(mock_llm, ep, output(), JUDGED)
    with session_scope() as s:
        from spira_server.db.models import Household
        s.get(Household, "h_042").paused = True
    out = s5_plan.finalize(ep, s4, now=JUDGED)
    assert out.published is None and out.status == "judged"
    with session_scope() as s:
        assert {t.status for t in s.execute(select(Task)).scalars()} == {"dropped"}


def test_pulled_plans(mock_llm):
    ep = ep9031()
    s5_plan.finalize(ep, h.s4_for(mock_llm, ep, output(), JUDGED), now=JUDGED)
    with session_scope() as s:
        assert [p["plan_version"] for p in s5_plan.pulled_plans(s, "h_042")] == [1]
        for t in s.execute(select(Task)).scalars():
            t.status = "ended"
        s.get(Plan, (ep, 1)).ack = {"plan_version": 1, "status": "admitted", "rejected_tasks": []}
    with session_scope() as s:
        assert s5_plan.pulled_plans(s, "h_042") == []


def test_t44_resume_finishes_mid_pipeline_episodes(monkeypatch):
    ep = ep9031()                                    # stage s2, reading, not judged
    called = []
    monkeypatch.setattr(runner, "run_from_s2", called.append)
    assert runner.resume() == [ep] and called == [ep]
    with session_scope() as s:
        from spira_server.db.models import EpisodeImage
        s.add(EpisodeImage(episode_id=ep, path="/tmp/x.png", read=False))
    called.clear()
    assert runner.resume() == [] and called == []    # unread images: the quiet timer will run it


def test_t51_and_line_states():
    t0 = clock.parse("2026-10-17T13:30:00+09:00")

    def r(dev, cmd, status, minutes=0, op="op_1", reason=None):
        at = t0 + timedelta(minutes=minutes)
        return ActionResult(dev, cmd, status, at, at, op, reason)

    two = [("cooktop_01", "child_lock"), ("plug_kettle", "off")]
    assert line_state(LineInput(actions=two, results=[r("cooktop_01", "child_lock", "completed")]))[0] == "running"
    done = [r("cooktop_01", "child_lock", "completed"), r("plug_kettle", "off", "completed")]
    assert line_state(LineInput(actions=two, results=done))[0] == "done"
    assert line_state(LineInput(actions=two, results=done, user_changed=True))[0] == "user_changed"
    part = [r("cooktop_01", "child_lock", "completed"), r("plug_kettle", "off", "failed")]
    assert line_state(LineInput(actions=two, results=part))[0] == "partial"
    late_running = [r("plug_kettle", "off", "completed", 1), r("plug_kettle", "off", "running", 2)]
    assert line_state(LineInput(actions=two[1:], results=late_running))[0] == "done"
    blocked = [r("plug_kettle", "off", "blocked", reason="plan_unconfirmed")]
    assert line_state(LineInput(actions=two[1:], results=blocked)) == ("blocked", "plan_unconfirmed")
    assert line_state(LineInput(actions=two, results=[]))[0] == "scheduled"
    assert line_state(LineInput(checked=False, card_stopped=True))[0] == "off"
    assert line_state(LineInput(card_stopped=True))[0] == "stopped"
    assert line_state(LineInput(rejected=True)) == ("failed", "rejected")
    assert line_state(LineInput(task_status="held"))[0] == "held"
    assert end_state(["restored", "not_needed"], True, True) == "restored"
    assert end_state(["withheld_end_not_observed", "restored"], True, True) == "withheld"
    assert end_state(["withheld_end_not_observed", "failed"], True, True) == "restore_failed"
    assert end_state(["skipped_user_changed"], True, True) == "kept_user_change"
    assert end_state([], False, True) == "none" and end_state([], True, False) is None


def test_waiting_for_after_window_opens(mock_llm):
    ep = ep9031()
    h.restart_card_ids(331)
    s5_plan.finalize(ep, h.s4_for(mock_llm, ep, output(), JUDGED), now=JUDGED)
    assert _cards(ep, JUDGED)[0]["summary"]["waiting_for"] is None
    assert _cards(ep, clock.parse("2026-10-17T13:31:00+09:00"))[0]["summary"]["waiting_for"] == "guest_arrived"


def test_card_text_variants():
    from spira_server.pipeline.s5_cards import card_text
    b = copy.deepcopy(h.INTENT_9120["bundles"][0])
    assert card_text(b, None)[1] == "가족 모임 준비를 알아챘어요. 일정을 캘린더에 넣어 두시면 그 시간에 맞춰 준비할게요"
    b["calendar_tags"] = ["가족 모임"]
    assert card_text(b, clock.parse("2026-11-07T18:00:00+09:00"))[1] == "토요일 가족 모임에 맞춰 집을 준비해 둘게요"
    b.update(intent_id="unclassified", calendar_tags=[])
    assert card_text(b, None)[1].startswith("이번 준비를 알아챘어요")
    with session_scope() as s:
        assert s.execute(select(CardLine)).first() is None


def test_room_mismatch_removes_only_other_room_actions():
    ep = ep9031()
    out = _finalize(ep, [_draft("t_mood#1", [{"device": "display_01", "cmd": "off"},
                                             {"device": "cooktop_01", "cmd": "child_lock"}],
                                {"time": "2026-10-17T13:30:00+09:00"}, room="거실")])
    assert out.dropped == {}
    [task] = _plan(ep)["tasks"]
    assert task["actions"] == [{"device": "display_01", "cmd": "off"}]       # the 주방 device is left out
    with session_scope() as s:
        row = s.get(Task, (ep, "t_mood#1"))
        assert row.meta["room_removed"] == [{"device": "cooktop_01", "cmd": "child_lock", "room": "주방"}]
        assert row.line == "t_mood#1"                                         # card line text unchanged
        assert s.execute(select(CardLine)).scalar_one().note is None          # nothing shown to the user
