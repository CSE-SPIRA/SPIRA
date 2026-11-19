"""find_time (spec §10.3): T16 calendar / holiday / habit / none, T58 holiday window already started."""

from datetime import timedelta

from spira_server import clock
from spira_server.config import get_config
from spira_server.db.engine import session_scope
from spira_server.db.models import Card, Case, Window
from spira_server.kb.lists import get_lists
from spira_server.pipeline.s4_time import find_time, habit_from_starts

from .factories import household

THU = clock.parse("2026-10-15T21:11:40+09:00")


def _find(bundle, shared=THU, now=THU):
    with session_scope() as s:
        return find_time(s, household_id="h_042", bundle=bundle, shared_at=shared, now=now, cfg=get_config(),
                         lists=get_lists())


def _bundle(intent_id="kid_birthday_party", window=None, tags=None):
    return {"intent_id": intent_id, "use_window": window, "calendar_tags": tags or []}


def test_calendar_window():
    household()
    w = _find(_bundle(window={"start": "2026-10-17T14:00:00+09:00", "end": "2026-10-17T17:00:00+09:00"},
                      tags=["생일"]))
    assert (w.source, clock.iso(w.start), clock.iso(w.end)) == (
        "calendar", "2026-10-17T14:00:00+09:00", "2026-10-17T17:00:00+09:00")


def test_past_calendar_window_skipped():
    household()
    assert _find(_bundle(window={"start": "2026-10-15T10:00:00+09:00", "end": "2026-10-15T12:00:00+09:00"})) is None


def test_holiday():
    household()
    shared = clock.parse("2026-12-20T10:00:00+09:00")
    w = _find(_bundle("christmas_party"), shared=shared, now=shared)
    assert (w.source, clock.iso(w.start), clock.iso(w.end)) == (
        "holiday", "2026-12-25T18:00:00+09:00", "2026-12-25T21:00:00+09:00")
    assert _find(_bundle("christmas_party"), shared=THU, now=THU) is None          # more than 14 days away


def test_t58_holiday_window_already_started_today():
    household()
    now = clock.parse("2026-12-25T18:30:00+09:00")
    assert _find(_bundle("christmas_party"), shared=now, now=now) is None          # 2027 is too far


def _habit_row(ep: str, start: str, n: int = 1, verdict: str = "match", tags=None):
    with session_scope() as s:
        from spira_server.kb import embedding

        from .s2_helpers import episode
        episode(s, ep, clock.parse(start) - timedelta(days=2), [("풍선", 1, "clue")])
        s.add(Card(id=f"nc_{ep}", episode_id=ep, bundle_index=0, ordinal=n, intent_id="kid_birthday_party",
                   template="common.v1", text="", updated_at=THU))
        s.flush()
        s.add(Window(id=f"ow_{ep}", episode_id=ep, card_id=f"nc_{ep}", scheduled_start=clock.parse(start)))
        s.add(Case(case_id=f"home_h_042_{ep}_{n}", source="this_home", items=["풍선"], intent_id="kid_birthday_party",
                   situation={}, when={"calendar_tags": tags or [], "executed_at": start}, household={"types": []},
                   basket_emb=embedding.embed_basket(["풍선"]), household_id="h_042", verdict=verdict))


def test_habit_two_matches_same_slot():
    household()
    _habit_row("ep_a", "2026-09-19T14:00:00+09:00")       # Sat 14:00
    _habit_row("ep_b", "2026-10-03T14:40:00+09:00")       # Sat 14:40 (within ± 1 h)
    w = _find(_bundle())
    assert (w.source, clock.iso(w.start), clock.iso(w.end)) == (
        "habit", "2026-10-17T14:00:00+09:00", "2026-10-17T17:00:00+09:00")        # lower median, next Saturday


def test_habit_needs_two_and_skips_other_tags_and_unclassified():
    household()
    _habit_row("ep_a", "2026-09-19T14:00:00+09:00")
    assert _find(_bundle()) is None                        # one match is not a habit
    _habit_row("ep_b", "2026-10-03T14:00:00+09:00", tags=["가족 모임"])
    assert _find(_bundle()) is None                        # other tags: not the same intent
    assert _find(_bundle("unclassified")) is None


def test_habit_rules_pure():
    cfg = get_config()
    sat = lambda h, m, d: clock.parse(f"2026-{d}T{h:02d}:{m:02d}:00+09:00")  # noqa: E731
    starts = [(sat(14, 0, "09-19"), THU), (sat(15, 30, "09-26"), THU), (sat(14, 30, "10-03"), THU)]
    w = habit_from_starts(starts, THU, THU, cfg)
    assert clock.iso(w.start) == "2026-10-17T14:00:00+09:00"   # slot = rows within 1 h of the slot's first row
    assert habit_from_starts([], THU, THU, cfg) is None
