"""Calendar intake and tagging (spec §8.5). Titles live only in memory for one request; only tags are stored.

    accepted = receive_calendar(household_id, events)     # step 1, one transaction; returns what to tag
    tag_events(accepted)                                   # steps 2-5, LLM outside any lock, revision guard

The route (`PUT /v1/households/{hid}/calendar`, S6) runs `tag_events` in the background after answering 202.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, create_model
from sqlalchemy import delete, select

from .. import clock
from ..db.engine import lock_household, session_scope
from ..db.models import CalendarEvent, CalendarRevision
from ..kb.lists import get_lists
from ..llm import prompts
from ..llm.client import call_with_retry, get_llm
from ..settings import get_settings

log = logging.getLogger(__name__)

# Called with (household_id) after tags are stored; spec §14 calendar re-runs are added with the re-run batch.
after_tagging: list = []


@dataclass
class CalendarInput:
    id: str
    title: str
    start: str
    end: str


@dataclass
class Accepted:
    household_id: str
    revision: int
    accepted: int
    to_tag: list[CalendarInput] = field(default_factory=list)


def fingerprint(title: str, start: str, end: str) -> str:
    key = get_settings().calendar_hmac_key.encode()
    return hmac.new(key, f"{title}\n{start}\n{end}".encode(), hashlib.sha256).hexdigest()


def receive_calendar(household_id: str, events: list[CalendarInput]) -> Accepted:
    with session_scope() as s:
        if lock_household(s, household_id) is None:
            raise LookupError(household_id)
        rev = s.get(CalendarRevision, household_id)
        if rev is None:
            rev = CalendarRevision(household_id=household_id, revision=0)
            s.add(rev)
        rev.revision += 1
        stored = {e.id: e for e in s.execute(
            select(CalendarEvent).where(CalendarEvent.household_id == household_id)).scalars()}
        incoming = {e.id for e in events}
        gone = [i for i in stored if i not in incoming]
        if gone:
            s.execute(delete(CalendarEvent).where(CalendarEvent.household_id == household_id,
                                                  CalendarEvent.id.in_(gone)))
        to_tag = []
        for e in events:
            fp = fingerprint(e.title, e.start, e.end)
            row = stored.get(e.id)
            if row is None:
                row = CalendarEvent(household_id=household_id, id=e.id, tags=[], tagged=False)
                s.add(row)
            elif row.fingerprint != fp:
                row.tags, row.tagged = [], False
            row.start, row.end, row.fingerprint = clock.parse(e.start), clock.parse(e.end), fp
            if not row.tagged:
                to_tag.append(e)
        return Accepted(household_id, rev.revision, len(events), to_tag)


def tagging_schema(ids: list[str]) -> type[BaseModel]:
    tags = tuple(get_lists().calendar_tags)
    event = create_model("EventTags", id=(Literal[tuple(ids)], ...),  # type: ignore[valid-type]
                         tags=(list[Literal[tags]], Field(default_factory=list, max_length=3)))  # type: ignore
    return create_model("CalendarTagging", events=(list[event], ...))  # type: ignore[valid-type]


def user_message(events: list[CalendarInput]) -> str:
    lines = []
    for e in events:
        st, en = clock.parse(e.start), clock.parse(e.end)
        lines.append(f"- {e.id} · {st.month}월 {st.day}일 ({clock.weekday_ko(st)}) "
                     f"{st.strftime('%H:%M')}~{en.strftime('%H:%M')} · {e.title}")
    return prompts.fill(prompts.text("cal_user.txt"), EVENTS="\n".join(lines))


def tag_events(accepted: Accepted) -> bool:
    """Returns True when tags were stored (False: nothing to tag, LLM failed, or a newer PUT owns the calendar)."""
    if not accepted.to_tag:
        return False
    ids = [e.id for e in accepted.to_tag]
    result = call_with_retry(
        get_llm(), stage="cal", system=prompts.system("cal"), user=user_message(accepted.to_tag),
        schema=tagging_schema(ids), retry_template=prompts.text("s1_retry.txt"), default=None,
    )
    if not result.ok:
        return False                                  # tagged stays false: retried at the next PUT
    tags = {e.id: list(dict.fromkeys(e.tags)) for e in result.value.events}
    with session_scope() as s:
        lock_household(s, accepted.household_id)
        rev = s.get(CalendarRevision, accepted.household_id)
        if rev is None or rev.revision != accepted.revision:
            return False                              # discard: a newer PUT owns the calendar
        for row in s.execute(select(CalendarEvent).where(CalendarEvent.household_id == accepted.household_id,
                                                         CalendarEvent.id.in_(ids))).scalars():
            row.tags, row.tagged = tags.get(row.id, []), True
    for hook in after_tagging:
        hook(accepted.household_id)
    return True
