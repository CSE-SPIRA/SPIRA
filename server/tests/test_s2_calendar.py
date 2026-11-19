"""Calendar intake and tagging (spec §8.5): T12 and T54, fingerprints, deletions, failure default."""

from sqlalchemy import select, text

from spira_server.db.engine import server_engine, session_scope
from spira_server.db.models import CalendarEvent, CalendarRevision
from spira_server.llm import prompts
from spira_server.pipeline.s2_calendar import CalendarInput, receive_calendar, tag_events, user_message

from .factories import fixture, household


def _events() -> list[CalendarInput]:
    return [CalendarInput(**e) for e in fixture("ep_9031/calendar.json")["events"]]


def _record(mock_llm, events, tags: dict[str, list[str]]):
    mock_llm.record("cal", prompts.system("cal"), user_message(events),
                    output={"events": [{"id": i, "tags": t} for i, t in tags.items()]})


def _stored() -> dict[str, tuple]:
    with session_scope() as s:
        return {e.id: (e.tags, e.tagged) for e in s.execute(select(CalendarEvent)).scalars()}


TAGS = {"c1": ["생일"], "c2": ["가족 모임"], "c3": ["회의"], "c4": [], "c5": []}


def test_t12_tags_and_no_titles(mock_llm):
    household()
    events = _events()
    assert user_message(events).splitlines()[1] == "- c1 · 10월 17일 (토) 14:00~17:00 · 지아 생일파티 🎂"
    _record(mock_llm, events, TAGS)
    acc = receive_calendar("h_042", events)
    assert (acc.accepted, acc.revision, len(acc.to_tag)) == (5, 1, 5)
    assert tag_events(acc) is True
    assert _stored() == {k: (v, True) for k, v in TAGS.items()}
    with server_engine().connect() as conn:                       # titles are never stored anywhere
        dump = " ".join(str(r) for r in conn.execute(text("SELECT * FROM calendar_events")))
    assert not any(e.title in dump for e in events)


def test_unchanged_events_keep_tags_changed_retagged_missing_deleted(mock_llm):
    household()
    events = _events()
    _record(mock_llm, events, TAGS)
    tag_events(receive_calendar("h_042", events))
    changed = [CalendarInput(e.id, "가족 모임 (장소 변경)" if e.id == "c2" else e.title, e.start, e.end)
               for e in events if e.id != "c5"]
    acc = receive_calendar("h_042", changed)
    assert [e.id for e in acc.to_tag] == ["c2"]
    assert _stored()["c2"] == ([], False)
    _record(mock_llm, acc.to_tag, {"c2": ["가족 모임"]})
    assert tag_events(acc)
    stored = _stored()
    assert "c5" not in stored and stored["c1"] == (["생일"], True) and stored["c2"] == (["가족 모임"], True)


def test_t54_older_tagging_result_discarded(mock_llm):
    household()
    events = _events()
    first = receive_calendar("h_042", events)
    second = receive_calendar("h_042", events)                   # a newer PUT while the first is tagging
    _record(mock_llm, events, TAGS)
    assert tag_events(second) is True
    with session_scope() as s:
        s.execute(select(CalendarEvent)).scalars()
        for e in s.execute(select(CalendarEvent)).scalars():
            e.tags = ["대청소"]
    assert tag_events(first) is False                             # revision 1 != 2: discarded
    assert all(t == ["대청소"] for t, _ in _stored().values())
    with session_scope() as s:
        assert s.get(CalendarRevision, "h_042").revision == 2


def test_failure_leaves_untagged_for_next_put(mock_llm):
    household()
    events = _events()
    mock_llm.record("cal", prompts.system("cal"), user_message(events), timeout=True)
    acc = receive_calendar("h_042", events)
    assert tag_events(acc) is False
    assert all(v == ([], False) for v in _stored().values())
    assert len(receive_calendar("h_042", events).to_tag) == 5     # same fingerprints, still untagged
