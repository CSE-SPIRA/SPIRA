"""S2 Context (spec §8.1–8.4): order time, this home (household types, unusual items, calendar) and KB neighbours.

Output stored in `episodes.context`:

    {"for_intent": {"order_time": {...}, "this_home": {...}, "kb_neighbors": {...}}, "snapshot": [case_id, ...],
     "kb_search": {...}}    (kb_search: display and replay only, never in the S3 message)

`this_home` is left out with HOME_CONTEXT=off, `kb_neighbors` with KB_MODE=off (spec §15).
"""

from __future__ import annotations

import logging
import statistics
import time
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from . import stage_times
from ..config import Config, get_config
from ..db.engine import kb_engine, session_scope
from ..db.models import CalendarEvent, Episode, Household, OrderItem
from ..kb import embedding
from ..kb.lists import KbLists, get_lists
from ..kb.search import KbCase, KbUnavailable, base_counts, search
from ..settings import Settings, get_settings

log = logging.getLogger(__name__)

NEVER = "이 집이 산 적 없는 종류"
HISTORY_EXCLUDED = ("paused_skip", "read_failed")


def order_time(shared_at: datetime) -> dict:
    return {"shared_at": clock.iso(shared_at), "weekday": clock.weekday_ko(shared_at)}


def item_types(s: Session, episode_id: str) -> list[OrderItem]:
    """Unmasked items in item order."""
    rows = s.execute(select(OrderItem).where(OrderItem.episode_id == episode_id, OrderItem.masked.is_(False))).scalars()
    return sorted(rows, key=lambda i: int(i.id.split("_")[1]))


# ---------------------------------------------------------------------------------------------- unusual items (§8.2)

def unusual_items(s: Session, ep: Episode, items: list[OrderItem], cfg: Config) -> dict:
    n = cfg.numbers
    since = ep.shared_at - timedelta(days=n.history_d)
    past_eps = s.execute(
        select(Episode.id).where(Episode.household_id == ep.household_id, Episode.id != ep.id,
                                 Episode.status.not_in(HISTORY_EXCLUDED),
                                 Episode.shared_at >= since, Episode.shared_at < ep.shared_at)
    ).scalars().all()
    past = s.execute(
        select(OrderItem.episode_id, OrderItem.type, OrderItem.qty)
        .where(OrderItem.episode_id.in_(past_eps), OrderItem.masked.is_(False))
    ).all() if past_eps else []
    episodes_with_items = {e for e, _, _ in past}
    if len(episodes_with_items) < n.min_orders:
        return {"status": "insufficient"}

    current = list(dict.fromkeys(i.type for i in items))
    past_types = sorted({t for _, t, _ in past})
    same = _similar_types(current, past_types, n.type_sim)
    unusual, usual = [], []
    for item in items:
        matches = same.get(item.type, set())
        hits = [(e, q) for e, t, q in past if t in matches]
        count = len({e for e, _ in hits})
        if count == 0:
            why = NEVER
        elif count < n.routine_min:
            why = f"90일에 {count}번 산 드문 물건"
        else:
            qtys = [q for _, q in hits if q is not None]
            med = statistics.median(qtys) if qtys else None
            why = (f"평소 {_num(med)}개 → 이번 {item.qty}개"
                   if med and item.qty is not None and item.qty >= n.spike * med else None)
        if why:
            unusual.append({"item": item.type, "why": why})
        else:
            usual.append(item.type)
    if not unusual:
        return {"status": "all_usual"}
    return {"status": "list", "items": unusual, "usual": usual}


def _similar_types(current: list[str], past: list[str], threshold: float) -> dict[str, set[str]]:
    """Equal string, or embed_basket([a])·embed_basket([b]) >= type_sim."""
    out = {t: {t} & set(past) for t in current}
    others = [p for p in past if p not in current]
    if not others or not current:
        return out
    vectors = embedding.embed_baskets([[t] for t in current + others])
    cur_v, oth_v = vectors[:len(current)], vectors[len(current):]
    for t, v in zip(current, cur_v):
        for p, w in zip(others, oth_v):
            if embedding.cosine(v, w) >= threshold:
                out[t].add(p)
    return out


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


# ---------------------------------------------------------------------------------------------------- calendar (§8.2)

def calendar_block(s: Session, ep: Episode, cfg: Config, lists: KbLists) -> list[dict]:
    start, end = ep.shared_at, ep.shared_at + timedelta(days=cfg.numbers.calendar_window_d)
    rows = s.execute(
        select(CalendarEvent).where(CalendarEvent.household_id == ep.household_id, CalendarEvent.tagged.is_(True),
                                    CalendarEvent.start >= start, CalendarEvent.start <= end)
        .order_by(CalendarEvent.start, CalendarEvent.id)
    ).scalars().all()
    shared_day = ep.shared_at.astimezone(clock.KST).date()
    out = []
    for e in rows:
        tags = list(e.tags or [])
        if not tags or all(t in lists.everyday_tags for t in tags):
            continue
        st, en = e.start.astimezone(clock.KST), e.end.astimezone(clock.KST)
        out.append({"id": e.id, "days_after": (st.date() - shared_day).days, "day": clock.weekday_ko(st),
                    "tags": tags, "start": st.strftime("%H:%M"), "end": en.strftime("%H:%M")})
    return out[: cfg.numbers.max_events]


# ------------------------------------------------------------------------------------------------ KB neighbours (§8.3)

def kb_neighbors(types: list[str], calendar: list[dict], household_types: list[str], settings: Settings,
                 cfg: Config, lists: KbLists) -> tuple[dict, list[str], dict]:
    """(kb_neighbors block for S3, case ids used, search record for display)."""
    n = cfg.numbers
    q = embedding.embed_basket(types)
    cases = search(kb_engine(), q, kb_version_number=settings.kb_version_number, sample=settings.kb_sample,
                   limit=n.search_limit)
    home = settings.home_context == "on"
    block, snapshot = summarize_neighbors(cases, types, calendar, household_types, home=home, n=n, lists=lists,
                                          sim_floor=n.sim_floor, max_use=n.max_use, base=base_rates(settings, n))
    return block, snapshot, search_record(cases, snapshot, calendar, household_types, home=home, n=n)


def search_record(cases: list[KbCase], used: list[str], calendar: list[dict], household_types: list[str], *,
                  home: bool, n) -> dict:
    """What the KB search returned, kept for display and replay only (§8.3 step 9). S3 never reads it."""
    cal_tags = {t for e in calendar for t in e["tags"]}
    house = set(household_types)
    kept = set(used)
    by_sim = sorted(cases, key=lambda c: (c.sim, c.case_id), reverse=True)
    top = []
    for c in by_sim[: n.search_record_top]:
        cal, hh = context_bonus(c, cal_tags, house, home, n)
        top.append({"case_id": c.case_id, "sim": round(c.sim, 4), "score": round(c.sim + cal + hh, 4),
                    "intent_id": c.intent_id, "intent_text": c.intent_text, "items": sorted(c.items),
                    "used": c.case_id in kept})
    return {"searched": len(cases), "sim_floor": n.sim_floor, "above_floor": sum(1 for c in cases if c.sim > n.sim_floor),
            "used": len(kept), "sims": [round(c.sim, 4) for c in by_sim], "top": top}


_BASE: dict[tuple[int, float], tuple[float, dict[str, int]]] = {}


def base_rates(settings: Settings, n) -> dict[str, int]:
    """Cases per intent among the searchable KB cases (R48), counted once and again after `base_refresh_min`: the
    KB grows under the same version while it is built."""
    key = (settings.kb_version_number, settings.kb_sample)
    hit = _BASE.get(key)
    if hit and time.monotonic() - hit[0] < n.base_refresh_min * 60:
        return hit[1]
    counts = base_counts(kb_engine(), kb_version_number=key[0], sample=key[1])
    _BASE[key] = (time.monotonic(), counts)
    return counts


def reset_base_cache() -> None:
    _BASE.clear()


def context_bonus(c: KbCase, cal_tags: set[str], house: set[str], home: bool, n) -> tuple[float, float]:
    """(calendar bonus, household bonus) of one case; both 0 when HOME_CONTEXT=off."""
    if not home:
        return 0.0, 0.0
    cal = n.w_cal if cal_tags & set(c.when.get("calendar_tags") or []) else 0.0
    hh = n.w_house if house & set(c.household.get("types") or []) else 0.0
    return cal, hh


def rank_similar(cases: list[KbCase], calendar: list[dict], household_types: list[str], *, home: bool, n,
                 sim_floor: float, max_use: int) -> tuple[list[KbCase], dict[str, float]]:
    """Cases above `sim_floor`, best `max_use` by score = sim + context bonus. Also returns every case's score."""
    cal_tags = {t for e in calendar for t in e["tags"]}
    house = set(household_types)
    scores = {c.case_id: c.sim + sum(context_bonus(c, cal_tags, house, home, n)) for c in cases}
    similar = [c for c in cases if c.sim > sim_floor]
    ranked = sorted(similar, key=lambda c: (scores[c.case_id], c.sim, c.case_id), reverse=True)[:max_use]
    return ranked, scores


def summarize_neighbors(cases: list[KbCase], types: list[str], calendar: list[dict], household_types: list[str], *,
                        home: bool, n, lists: KbLists, sim_floor: float, max_use: int,
                        base: dict[str, int] | None = None) -> tuple[dict, list[str]]:
    """The kb_neighbors block from searched cases (§8.3). dry_run.py calls this again with other floors and caps.
    With `base` (cases per intent in the whole KB) each count also carries `share` and `base_share`, and `none`
    always has a row (R48)."""
    similar_n = sum(1 for c in cases if c.sim > sim_floor)
    if similar_n < n.min_similar:
        return {"similar_count": similar_n, "note": "비슷한 사례가 거의 없음"}, []
    ranked, scores = rank_similar(cases, calendar, household_types, home=home, n=n, sim_floor=sim_floor,
                                  max_use=max_use)
    counts = Counter(c.intent_id for c in ranked)
    best: dict[str, KbCase] = {}
    for c in ranked:                               # ranked best first
        best.setdefault(c.intent_id, c)
    order = sorted(counts, key=lambda i: (-counts[i], -scores[best[i].case_id], best[i].case_id))
    reps = pick_reps(order, counts, len(ranked), n.cover, n.none_min, n.max_reps)
    examples = []
    for intent_id in reps:
        c = best[intent_id]
        examples.append({
            "case_id": c.case_id, "items": sorted(c.items), "intent_id": c.intent_id,
            "intent_text": c.intent_text, "situation": c.situation,
            "calendar_tags": list(c.when.get("calendar_tags") or []),
            "case_household_types": list(c.household.get("types") or []),
        })
    rows = [{"intent_id": i, "name": lists.intent_name(i), "n": counts[i]} for i in order]
    block: dict = {"similar_count": len(ranked), "intent_counts": rows, "examples": examples, "note": None}
    if base:
        total = sum(base.values())
        if "none" not in counts:
            rows.append({"intent_id": "none", "name": lists.intent_name("none"), "n": 0})
        for r in rows:
            r["share"] = round(r["n"] / len(ranked), 4)
            r["base_share"] = round(base.get(r["intent_id"], 0) / total, 4)
        block["base_total"] = total
    return block, [c.case_id for c in ranked]


def pick_reps(order: list[str], counts: Counter, total: int, cover: float, none_min: float, max_reps: int) -> list[str]:
    """Intents by count until the covered share reaches `cover` (at most `max_reps`); `none` is always included when
    its share is at least `none_min` (it takes the last place if the list is full)."""
    reps: list[str] = []
    covered = 0
    for intent_id in order:
        if len(reps) >= max_reps or covered / total >= cover:
            break
        reps.append(intent_id)
        covered += counts[intent_id]
    if "none" in counts and "none" not in reps and counts["none"] / total >= none_min:
        if len(reps) >= max_reps:
            reps[-1] = "none"
        else:
            reps.append("none")
    return reps


# ---------------------------------------------------------------------------------------------------------- build

def build_context(episode_id: str) -> dict:
    """Reads committed state; no lock is held during embedding or KB calls (spec §2.4)."""
    settings, cfg, lists = get_settings(), get_config(), get_lists()
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        household = s.get(Household, ep.household_id)
        items = item_types(s, episode_id)
        for_intent: dict = {"order_time": order_time(ep.shared_at)}
        calendar: list[dict] = []
        types_h = list(household.household_types or [])
        if settings.home_context == "on":
            calendar = calendar_block(s, ep, cfg, lists)
            for_intent["this_home"] = {
                "household_types": types_h,
                "unusual_items": unusual_items(s, ep, items, cfg),
                "calendar": calendar,
            }
    snapshot: list[str] = []
    out: dict = {"for_intent": for_intent, "snapshot": snapshot}
    if settings.kb_mode == "on":
        types = list(dict.fromkeys(i.type for i in items))
        for_intent["kb_neighbors"], out["snapshot"], out["kb_search"] = kb_neighbors(
            types, calendar, types_h, settings, cfg, lists)
    return out


def run(episode_id: str) -> bool:
    """Build and store the context (stage s2). Returns False when S2 failed and the episode was closed as judged."""
    try:
        context = build_context(episode_id)
    except KbUnavailable as e:
        _fail(episode_id, f"KB unavailable: {e}")
        return False
    with session_scope() as s:
        ep = s.execute(select(Episode).where(Episode.id == episode_id).with_for_update()).scalar_one()
        ep.context = context
        ep.stage = "s2"
        stage_times.mark(ep, "s2")
    return True


def _fail(episode_id: str, message: str) -> None:
    with session_scope() as s:
        ep = s.execute(select(Episode).where(Episode.id == episode_id).with_for_update()).scalar_one()
        ep.status, ep.judged, ep.stage = "judged", True, "done"
        stage_times.mark(ep, "s2")
        ep.error = {"stage": "s2", "message": message}
        ep.intent = {"bundles": [], "unbundled": [], "none_reason": "error", "error": {"stage": "s2"}}
