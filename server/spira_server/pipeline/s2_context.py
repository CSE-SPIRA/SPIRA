"""S2 Context (spec §8.1–8.4): order time, this home (household types, unusual items, calendar) and KB neighbours.

Output stored in `episodes.context`:

    {"for_intent": {"order_time": {...}, "this_home": {...}, "kb_neighbors": {...}}, "snapshot": [case_id, ...]}

`this_home` is left out with HOME_CONTEXT=off, `kb_neighbors` with KB_MODE=off (spec §15).
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..config import Config, get_config
from ..db.engine import kb_engine, session_scope
from ..db.models import CalendarEvent, Episode, Household, OrderItem
from ..kb import embedding
from ..kb.lists import KbLists, get_lists
from ..kb.search import KbCase, KbUnavailable, search
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
                 cfg: Config, lists: KbLists) -> tuple[dict, list[str]]:
    n = cfg.numbers
    q = embedding.embed_basket(types)
    cases = search(kb_engine(), q, kb_version_number=settings.kb_version_number, sample=settings.kb_sample,
                   limit=n.search_limit)
    similar = [c for c in cases if c.sim > n.sim_floor]
    if len(similar) < n.min_similar:
        return {"similar_count": len(similar), "note": "비슷한 사례가 거의 없음"}, []

    home = settings.home_context == "on"
    cal_tags = {t for e in calendar for t in e["tags"]}
    house = set(household_types)

    def score(c: KbCase) -> float:
        bonus = 0.0
        if home and cal_tags & set(c.when.get("calendar_tags") or []):
            bonus += n.w_cal
        if home and house & set(c.household.get("types") or []):
            bonus += n.w_house
        return c.sim + bonus

    ranked = sorted(similar, key=lambda c: (score(c), c.sim, c.case_id), reverse=True)[: n.max_use]
    counts = Counter(c.intent_id for c in ranked)
    best: dict[str, KbCase] = {}
    for c in ranked:                               # ranked best first
        best.setdefault(c.intent_id, c)
    order = sorted(counts, key=lambda i: (-counts[i], -score(best[i]), best[i].case_id))
    reps = pick_reps(order, counts, len(ranked), n.cover, n.none_min, n.max_reps)
    order_set = set(types)
    examples = []
    for intent_id in reps:
        c = best[intent_id]
        shared = sorted(order_set & set(c.items))
        examples.append({
            "case_id": c.case_id, "items": sorted(c.items), "intent_id": c.intent_id,
            "intent_text": c.intent_text, "situation": c.situation,
            "calendar_tags": list(c.when.get("calendar_tags") or []),
            "case_household_types": list(c.household.get("types") or []),
            "overlap": {"k": len(shared), "n": len(c.items), "items": shared},
        })
    return {
        "similar_count": len(ranked),
        "intent_counts": [{"intent_id": i, "name": lists.intent_name(i), "n": counts[i]} for i in order],
        "examples": examples,
        "note": None,
    }, [c.case_id for c in ranked]


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
    if settings.kb_mode == "on":
        types = list(dict.fromkeys(i.type for i in items))
        for_intent["kb_neighbors"], snapshot = kb_neighbors(types, calendar, types_h, settings, cfg, lists)
    return {"for_intent": for_intent, "snapshot": snapshot}


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
    return True


def _fail(episode_id: str, message: str) -> None:
    with session_scope() as s:
        ep = s.execute(select(Episode).where(Episode.id == episode_id).with_for_update()).scalar_one()
        ep.status, ep.judged, ep.stage = "judged", True, "done"
        ep.error = {"stage": "s2", "message": message}
        ep.intent = {"bundles": [], "unbundled": [], "none_reason": "error", "error": {"stage": "s2"}}
