"""Build ep_9031 in the DB for S2 tests: the episode, its items, the calendar and 90 days of history."""

from __future__ import annotations

from datetime import timedelta

from spira_server import clock
from spira_server.db.engine import session_scope
from spira_server.db.models import CalendarEvent, Episode, OrderItem

from .factories import household

SHARED = clock.parse("2026-10-15T21:00:08+09:00")
ITEMS = [  # (type, qty, label) in item order, from the S1 fixture
    ("딸기", 2, "care"), ("컵케이크 믹스", None, "care"), ("휘핑크림", 1, "care"), ("세탁 세제", 1, "clue"),
    ("로션", 1, "clue"), ("풍선", 1, "clue"), ("케이크 토퍼", 1, "clue"), ("고깔모자", 6, "clue"),
    ("아이싱 펜", 1, "care"),
]
CAL_TAGS = {"c1": ["생일"], "c2": ["가족 모임"], "c3": ["회의"], "c4": [], "c5": []}


def episode(s, eid: str, at, items: list[tuple], status: str = "judged", hid: str = "h_042") -> None:
    s.add(Episode(id=eid, household_id=hid, status=status, shared_at=at, received_at=at, source_ids=[],
                  judged=status != "reading", plan_version=0, next_item_n=len(items) + 1, next_task_n=1,
                  next_card_ordinal=1, rerun_pending=False, stage="s1" if status == "reading" else "done"))
    s.flush()
    for n, (t, q, label) in enumerate(items, start=1):
        s.add(OrderItem(episode_id=eid, id=f"it_{n}", name=t, type=t, grp=None, label=label, qty=q, masked=False,
                        attributes=[]))


def history(s, n_orders: int = 12) -> None:
    """Past 90 days: 세탁 세제 and 로션 3+ times, 딸기 4 times (qty 1), 컵케이크 믹스 and 휘핑크림 once."""
    for k in range(n_orders):
        at = SHARED - timedelta(days=5 + k * 6)
        items = [("우유", 1, "care"), ("계란", 1, "care")]
        if k < 4:
            items += [("딸기", 1, "care"), ("세탁 세제", 1, "clue"), ("로션", 1, "clue")]
        if k == 5:
            items += [("컵케이크 믹스", 1, "care"), ("휘핑크림", 1, "care")]
        episode(s, f"ep_h{k}", at, items)


def ep9031(with_history: bool = True, with_calendar: bool = True) -> str:
    household()
    with session_scope() as s:
        if with_history:
            history(s)
        episode(s, "ep_9031", SHARED, ITEMS, status="reading")
        if with_calendar:
            for e in data_calendar():
                s.add(CalendarEvent(household_id="h_042", id=e["id"], start=clock.parse(e["start"]),
                                    end=clock.parse(e["end"]), tags=CAL_TAGS[e["id"]], tagged=True,
                                    fingerprint="x"))
    return "ep_9031"


def data_calendar() -> list[dict]:
    from .factories import fixture
    return fixture("ep_9031/calendar.json")["events"]

