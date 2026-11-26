"""S3 Intent judgement (spec §9): one LLM call; code checks only the format and fills times and tags.

    build_intent_message(context, items)       the user message (blocks of s3_blocks.yaml)
    build_schema(item_types, cal_ids, ids)      Pydantic schema with this order's enums
    judge_from_context(context, items, llm)     the whole step without the DB (evaluation, spec §15)
    run(episode_id)                             read context + items, judge, store `episodes.intent`

`items` are unmasked items in item order: dicts with type, qty, attributes.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, create_model
from sqlalchemy import select

from .. import clock
from . import stage_times
from ..config import get_config
from ..db.engine import session_scope
from ..db.models import Episode
from ..kb.lists import get_lists
from ..llm import prompts
from ..llm.client import LLM, call_with_retry, get_llm
from .s2_context import item_types

log = logging.getLogger(__name__)

SITUATION_KEYS = ("event", "guests", "activity", "theme")
SHOWN_ATTRS = ("테마", "포장", "가공")


# ---------------------------------------------------------------------------------------------- message (§9.3)

def _blocks() -> dict:
    return prompts.blocks("s3_blocks.yaml")


def _item_line(item: dict, unknown: str) -> str:
    qty = item.get("qty")
    line = f"- {item['type']} × {qty if qty is not None else unknown}"
    attrs = [a for a in item.get("attributes") or [] if a.get("key") in SHOWN_ATTRS]
    if attrs:
        line += " [" + ", ".join(f"{a['key']}: {a['value']}" for a in attrs) + "]"
    return line


def build_intent_message(context: dict, items: list[dict]) -> str:
    b = _blocks()
    none_word, unknown = b["none_word"], b["unknown_qty"]
    fi = context["for_intent"]
    parts: list[str] = []

    parts.append("\n".join([b["order"]["header"], b["order"]["how"], *(_item_line(i, unknown) for i in items)]))

    shared = clock.parse(fi["order_time"]["shared_at"])
    parts.append("\n".join([b["order_time"]["header"], prompts.fill(
        b["order_time"]["line"], MONTH=shared.month, DAY=shared.day, WEEKDAY=fi["order_time"]["weekday"],
        HH=f"{shared.hour:02d}", MM=f"{shared.minute:02d}")]))

    home = fi.get("this_home")
    if home is not None:
        if home.get("household_types"):
            h = b["household"]
            parts.append("\n".join([h["header"], h["how"], ", ".join(home["household_types"])]))
        u, unusual = b["unusual"], home.get("unusual_items") or {"status": "insufficient"}
        if unusual["status"] == "list":
            lines = [u["header"], u["how"], *(f"- {r['item']}: {r['why']}" for r in unusual["items"])]
            if unusual.get("usual"):
                lines.append(prompts.fill(u["usual_line"], ITEMS=", ".join(unusual["usual"])))
            parts.append("\n".join(lines))
        else:
            empty = u["empty_insufficient"] if unusual["status"] == "insufficient" else u["empty_all_usual"]
            parts.append("\n".join([u["header"], empty]))
        c = b["calendar"]
        if home.get("calendar"):
            parts.append("\n".join([c["header"], c["how"], *(prompts.fill(
                c["line"], ID=e["id"], DAYS=e["days_after"], WEEKDAY=e["day"], START=e["start"], END=e["end"],
                TAGS=", ".join(e["tags"])) for e in home["calendar"])]))
        else:
            parts.append("\n".join([c["header"], c["empty"]]))

    kb = fi.get("kb_neighbors")
    if kb is not None:
        k = b["kb"]
        if kb.get("note") or not kb.get("intent_counts"):
            parts.append("\n".join([k["header"], prompts.fill(k["few"], N=kb.get("similar_count", 0))]))
        else:
            lines = [k["header"], k["how"], "", *kb_count_lines(kb, k)]
            for i, ex in enumerate(kb["examples"], start=1):
                sit = ex.get("situation") or {}
                lines += ["", prompts.fill(
                    k["example"], I=i, NAME=get_lists().intent_name(ex["intent_id"]), INTENT_ID=ex["intent_id"],
                    ITEMS=", ".join(ex["items"]), INTENT_TEXT=ex.get("intent_text") or none_word,
                    EVENT=sit.get("event") or none_word, GUESTS=sit.get("guests") or none_word,
                    ACTIVITY=sit.get("activity") or none_word, THEME=sit.get("theme") or none_word,
                    TAGS=", ".join(ex.get("calendar_tags") or []) or none_word,
                    TYPES=", ".join(ex.get("case_household_types") or []) or none_word)]
            parts.append("\n".join(lines))
    return "\n\n".join(parts) + "\n"


def _pct(x: float) -> str:
    return "1% 미만" if 0 < x < 0.005 else f"{round(x * 100)}%"


def kb_count_lines(kb: dict, k: dict) -> list[str]:
    """Counts of the kept cases; with base rates one line per intent, `none` last (R48)."""
    rows = kb["intent_counts"]
    if "base_total" not in kb:
        return [prompts.fill(k["counts"], N=kb["similar_count"],
                             COUNTS=" · ".join(f"{c['name']} {c['n']}" for c in rows))]
    rows = [r for r in rows if r["intent_id"] != "none"] + [r for r in rows if r["intent_id"] == "none"]
    return [prompts.fill(k["counts_header"], N=kb["similar_count"], TOTAL=f"{kb['base_total']:,}"),
            *(prompts.fill(k["count_line"], NAME=r["name"], N=r["n"], SHARE=_pct(r["share"]),
                           BASE=_pct(r["base_share"])) for r in rows)]


# ----------------------------------------------------------------------------------------------- schema (§9.4)

def build_schema(item_types: list[str], cal_ids: list[str], intent_ids: list[str]) -> type[BaseModel]:
    item_t = Literal[tuple(dict.fromkeys(item_types))]  # type: ignore[valid-type]
    basis_t = Literal[tuple(dict.fromkeys(item_types + cal_ids + ["가구 유형"]))]  # type: ignore[valid-type]
    cal_t = (Literal[tuple(cal_ids)] | None) if cal_ids else None  # type: ignore[valid-type]
    situation = create_model("Situation", **{k: (str | None, None) for k in SITUATION_KEYS})
    basis = create_model(
        "Basis", intent=(list[basis_t], Field(min_length=1)),
        **{k: (list[basis_t], Field(default_factory=list)) for k in SITUATION_KEYS})
    bundle = create_model(
        "Bundle",
        intent_id=(Literal[tuple(intent_ids + ["unclassified"])], ...),  # type: ignore[valid-type]
        intent_text=(str, ...),
        items=(list[item_t], Field(min_length=1)),
        situation=(situation, ...),
        basis=(basis, ...),
        calendar_event_id=(cal_t, None),
    )
    return create_model("IntentDecision", bundles=(list[bundle], ...), none_reason=(str | None, None))


# -------------------------------------------------------------------------------------------- format check (§9.5)

WORD_SEPARATORS = re.compile(r"[\s,·・/、]+")


def key_word(value: str) -> str:
    """The value itself, or for several words its longest word. Words are split on spaces and the list marks
    `,` `·` `/` (spec §9.5): "하츄핑, 공주, 핑크" -> "하츄핑"."""
    words = [w for w in WORD_SEPARATORS.split(value) if w]
    return max(words, key=len) if len(words) > 1 else value.strip()


def in_text(value: str, text: str) -> bool:
    """A situation value counts as written in intent_text when, ignoring spaces and list marks, the whole value is
    there ("하츄핑, 공주, 핑크" ~ "하츄핑·공주·핑크"), or its key word is."""
    squash = lambda s: WORD_SEPARATORS.sub("", s)  # noqa: E731
    return squash(value) in squash(text) or key_word(value) in text


def calendar_mismatch(intent_id: str, event_tags: list[str] | None) -> bool:
    """A linked event whose tags share nothing with the intent's related tags (spec §9.5, R44). Checked only for
    intents that have related tags; unclassified and intents without related tags may link any event."""
    if event_tags is None or intent_id == "unclassified":
        return False
    related = next((set(i.related_tags) for i in get_lists().intents if i.id == intent_id), set())
    return bool(related) and not related & set(event_tags)


def calendar_error(n: int, intent_id: str, event_id: str, event_tags: list[str]) -> str:
    intent = next((i for i in get_lists().intents if i.id == intent_id), None)
    name = intent.name if intent else intent_id
    related = ", ".join(intent.related_tags) if intent else ""
    tags = ", ".join(event_tags) or "태그 없음"
    return (f"묶음 {n}의 일정 {event_id}({tags})는 이 의도({name})와 맞는 행사가 아니다 (맞는 태그: {related}). "
            "물건이 가리키는 행사의 일정이 없으면 calendar_event_id는 null로 둔다")


def format_check(decision: BaseModel, event_tags: dict[str, list[str]] | None = None) -> list[str]:
    """Spec §9.5. `event_tags` (calendar id -> tags) turns on the calendar check (R44)."""
    errors: list[str] = []
    seen: dict[str, int] = {}
    intents: dict[str, int] = {}
    for n, bundle in enumerate(decision.bundles, start=1):
        for item in dict.fromkeys(bundle.items):
            if item in seen and seen[item] != n:
                errors.append(f'물건 "{item}": 묶음 {seen[item]}과 묶음 {n}에 함께 있다. '
                              "물건 하나는 한 묶음에만 넣는다")
            seen.setdefault(item, n)
        if bundle.intent_id != "unclassified":
            if bundle.intent_id in intents:
                errors.append(f"묶음 {intents[bundle.intent_id]}과 묶음 {n}의 intent_id가 같다 ({bundle.intent_id}). "
                              "같은 의도는 한 묶음으로 합친다")
            intents.setdefault(bundle.intent_id, n)
        if event_tags is not None and bundle.calendar_event_id:
            tags = event_tags.get(bundle.calendar_event_id)
            if calendar_mismatch(bundle.intent_id, tags):
                errors.append(calendar_error(n, bundle.intent_id, bundle.calendar_event_id, tags or []))
        for key in SITUATION_KEYS:
            value = getattr(bundle.situation, key)
            if value and not in_text(value, bundle.intent_text):
                errors.append(f'묶음 {n}의 {key} "{value}": intent_text에 없다. '
                              "채운 상황 칸을 intent_text에 모두 담는다")
    reason = (decision.none_reason or "").strip()
    if not decision.bundles and not reason:
        errors.append("bundles가 비었는데 none_reason이 없다. 의도가 없으면 이유를 한 문장으로 쓴다")
    if decision.bundles and reason:
        errors.append("bundles가 있는데 none_reason도 있다. 의도가 있으면 none_reason은 null로 둔다")
    return errors


# ------------------------------------------------------------------------------------------------- judge (§9.1)

def judge_from_context(context: dict, items: list[dict], llm: LLM | None = None,
                       episode_id: str | None = None) -> dict:
    """Spec §9.1 steps 1-7 on stored values only (no DB): the same context can be fed to several models."""
    types = list(dict.fromkeys(i["type"] for i in items))
    calendar = (context["for_intent"].get("this_home") or {}).get("calendar") or []
    cal_ids = [e["id"] for e in calendar]
    schema = build_schema(types, cal_ids, get_lists().intent_ids)
    tags_by_id = {e["id"]: list(e.get("tags") or []) for e in calendar}
    attempts = {"n": 0}

    def check(decision: BaseModel) -> list[str]:
        # The calendar check asks once; a link still wrong after the retry is removed below, not failed (R44).
        attempts["n"] += 1
        return format_check(decision, tags_by_id if attempts["n"] == 1 else None)

    result = call_with_retry(
        llm or get_llm(), stage="s3", system=prompts.system("s3"), user=build_intent_message(context, items),
        schema=schema, retry_template=prompts.text("s3_retry.txt"), default=None, episode_id=episode_id,
        check=check,
    )
    if not result.ok:
        return {"bundles": [], "unbundled": types, "none_reason": "format_fail",
                "error": {"stage": "s3", "outcome": result.outcome, "errors": result.errors}}

    decision = result.value
    notes: list[str] = []
    bundles: list[dict] = []
    for n, b in enumerate(decision.bundles, start=1):
        situation = b.situation.model_dump()
        basis = b.basis.model_dump()
        for key in SITUATION_KEYS:
            if situation[key] and not basis[key]:
                notes.append(f"bundle {n}: {key} without basis -> null")
                situation[key] = None
        event_id = b.calendar_event_id
        if event_id and calendar_mismatch(b.intent_id, tags_by_id.get(event_id)):
            notes.append(f"bundle {n}: calendar {event_id} does not match {b.intent_id} -> unlinked")
            event_id = None
        bundles.append({"intent_id": b.intent_id, "intent_text": b.intent_text,
                        "items": list(dict.fromkeys(b.items)), "situation": situation, "basis": basis,
                        "calendar_event_id": event_id, "calendar_tags": [], "use_window": None})
    max_bundles = get_config().numbers.max_bundles
    keep = sorted(range(len(bundles)), key=lambda i: (-len(bundles[i]["items"]), i))[:max_bundles]
    bundles = [bundles[i] for i in sorted(keep)]

    shared_day = clock.parse(context["for_intent"]["order_time"]["shared_at"]).date()
    by_id = {e["id"]: e for e in calendar}
    for b in bundles:
        event = by_id.get(b["calendar_event_id"] or "")
        if event:
            b["calendar_tags"] = list(event["tags"])
            b["use_window"] = use_window(shared_day, event)
    in_bundles = {t for b in bundles for t in b["items"]}
    return {"bundles": bundles, "unbundled": [t for t in types if t not in in_bundles],
            "none_reason": None if bundles else (decision.none_reason or None),
            "error": {"notes": notes} if notes else None}


def use_window(shared_day: date, event: dict) -> dict:
    """Absolute start/end of a calendar block entry (shared date + days_after, HH:MM in Asia/Seoul)."""
    day = shared_day + timedelta(days=event["days_after"])

    def at(hhmm: str) -> datetime:
        h, m = (int(x) for x in hhmm.split(":"))
        return datetime(day.year, day.month, day.day, h, m, tzinfo=clock.KST)

    start, end = at(event["start"]), at(event["end"])
    if end <= start:
        end += timedelta(days=1)
    return {"start": clock.iso(start), "end": clock.iso(end)}


def item_dicts(rows) -> list[dict]:
    return [{"item_id": r.id, "type": r.type, "qty": r.qty, "attributes": r.attributes or []} for r in rows]


def run(episode_id: str) -> dict:
    """Judge a stored episode and store `episodes.intent` (stage stays s2 until S5 publishes, spec §2.4)."""
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        context = ep.context
        items = item_dicts(item_types(s, episode_id))
    intent = judge_from_context(context, items, episode_id=episode_id)
    with session_scope() as s:
        ep = s.execute(select(Episode).where(Episode.id == episode_id).with_for_update()).scalar_one()
        ep.intent = intent
        stage_times.mark(ep, "s3")
    return intent
