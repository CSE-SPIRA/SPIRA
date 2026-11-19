"""S1 Order intake and extraction (spec §7).

    receive_capture(...)   POST /v1/orders: group the capture into an episode, store images, restart the quiet timer
    on_quiet(episode_id)   quiet_timer: read unread images with one LLM call per pass, post-process, merge, store
    recover()              on start: reschedule quiet timers of episodes with unread images (spec §2.3)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock, scheduler
from ..config import Config, get_config
from ..db.engine import lock_household, next_id, session_scope
from ..db.models import Episode, EpisodeImage, EpisodeSource, Household, Order, OrderItem
from ..llm import prompts
from ..llm.client import call_with_retry, get_llm
from ..store import images as image_store
from . import runner

log = logging.getLogger(__name__)

OPEN_EXCLUDED = ("closed", "paused_skip")
ATTR_KEYS = ("재질", "포장", "가공", "보관", "테마")
SENSITIVE_KINDS = ("의약품·의약외품", "건강 상태", "성·피임", "민감한 책·콘텐츠", "신체 보정·의료")


# --------------------------------------------------------------------------------------------------------------------
# Receive (spec §7.1)
# --------------------------------------------------------------------------------------------------------------------

@dataclass
class Accepted:
    episode_id: str
    status: str
    duplicate: bool          # True -> 200 (same source_id), False -> 202


class UnknownHousehold(LookupError):
    pass


def receive_capture(household_id: str, images: list[bytes], shared_at: datetime | None,
                    source_id: str | None) -> Accepted:
    """Images are already validated by the route (count, type, size)."""
    cfg = get_config()
    now = clock.now()
    with session_scope() as s:
        household = lock_household(s, household_id)
        if household is None:
            raise UnknownHousehold(household_id)
        if source_id:
            seen = s.get(EpisodeSource, (household_id, source_id))
            if seen is not None:
                ep = s.get(Episode, seen.episode_id)
                return Accepted(ep.id, ep.status, duplicate=True)

        at = shared_at or now
        at = min(max(at, now - timedelta(days=1)), now)

        if household.paused:
            ep = _new_episode(s, household_id, at, now, status="paused_skip")
            _add_source(s, ep, source_id)
            return Accepted(ep.id, ep.status, duplicate=False)

        ep = _open_group(s, household_id, at, cfg) or _new_episode(s, household_id, at, now, status="received")
        for data in images:
            s.add(EpisodeImage(episode_id=ep.id, path=image_store.save(ep.id, data), read=False))
        _add_source(s, ep, source_id)
        ep.quiet_due = now + timedelta(seconds=cfg.numbers.quiet_s)
        result = Accepted(ep.id, ep.status, duplicate=False)
        due = ep.quiet_due
    scheduler.schedule_quiet(result.episode_id, due)
    return result


def _new_episode(s: Session, household_id: str, shared_at: datetime, now: datetime, status: str) -> Episode:
    ep = Episode(id=next_id(s, "ep", "episode_id_seq"), household_id=household_id, status=status,
                 shared_at=shared_at, received_at=now, source_ids=[], judged=False, plan_version=0,
                 next_item_n=1, next_task_n=1, next_card_ordinal=1, rerun_pending=False)
    s.add(ep)
    s.flush()
    return ep


def _add_source(s: Session, ep: Episode, source_id: str | None) -> None:
    if not source_id:
        return
    s.add(EpisodeSource(household_id=ep.household_id, source_id=source_id, episode_id=ep.id))
    ep.source_ids = [*ep.source_ids, source_id]


def _open_group(s: Session, household_id: str, at: datetime, cfg: Config) -> Episode | None:
    window = timedelta(hours=cfg.numbers.group_window_h)
    rows = s.execute(
        select(Episode)
        .where(Episode.household_id == household_id, Episode.status.not_in(OPEN_EXCLUDED),
               Episode.shared_at >= at - window, Episode.shared_at <= at + window)
        .order_by(Episode.shared_at.desc(), Episode.id.desc())
        .with_for_update()
    ).scalars().all()
    return rows[0] if rows else None


# --------------------------------------------------------------------------------------------------------------------
# LLM schema (spec §7.3)
# --------------------------------------------------------------------------------------------------------------------

class Attribute(BaseModel):
    key: Literal[ATTR_KEYS]  # type: ignore[valid-type]
    value: str
    source: str


class Order_(BaseModel):
    order_no: str | None = None
    mall: str | None = None
    eta: str | None = None


def item_model(groups: list[str]) -> type[BaseModel]:
    return create_model(
        "Item",
        name=(str, ...),
        type=(str, ...),
        group=(Literal[tuple(groups)] | None, ...),  # type: ignore[valid-type]
        qty=(int | None, Field(None, ge=1, le=999)),
        deal=(str | None, None),
        order_no=(str | None, None),
        attributes=(list[Attribute], []),
        sensitive_kind=(Literal[SENSITIVE_KINDS] | None, None),  # type: ignore[valid-type]
    )


def extraction_model(groups: list[str]) -> type[BaseModel]:
    item = item_model(groups)
    return create_model("OrderExtraction", items=(list[item], ...), orders=(list[Order_], []))  # type: ignore[valid-type]


@dataclass
class Parsed:
    items: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_extraction(raw: Any, groups: list[str]) -> Parsed:
    """Two-step validation: each item on its own; an item that fails is dropped alone (spec §7.3)."""
    out = Parsed()
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        out.errors.append("items 목록이 없다. {\"items\": [...], \"orders\": [...]} 형식으로 답해야 한다.")
        return out
    item = item_model(groups)
    for i, entry in enumerate(raw["items"], start=1):
        try:
            out.items.append(item.model_validate(entry).model_dump())
        except ValidationError as e:
            out.errors.extend(_item_errors(i, entry, e))
    for entry in raw.get("orders") or []:
        try:
            out.orders.append(Order_.model_validate(entry).model_dump())
        except ValidationError:
            pass
    return out


def _item_errors(i: int, entry: Any, e: ValidationError) -> list[str]:
    msgs = []
    for err in e.errors():
        loc = err.get("loc", ())
        key = loc[0] if loc else ""
        value = entry.get(key) if isinstance(entry, dict) and isinstance(key, str) else None
        if key == "group":
            msgs.append(f'물건 {i}의 group "{value}"은 상품군 목록에 없다')
        elif key == "sensitive_kind":
            msgs.append(f'물건 {i}의 sensitive_kind "{value}"은 다섯 범주에 없다')
        elif key == "qty":
            msgs.append(f"물건 {i}의 qty는 1~999의 정수이거나 null이어야 한다")
        elif key == "attributes":
            msgs.append(f"물건 {i}의 attributes 형식이 틀렸다 (key는 재질·포장·가공·보관·테마 중 하나)")
        else:
            msgs.append(f"물건 {i}의 {'.'.join(map(str, loc)) or '형식'}: {err.get('msg', '')}")
    return msgs


# --------------------------------------------------------------------------------------------------------------------
# Post-processing (spec §7.4)
# --------------------------------------------------------------------------------------------------------------------

UNIT_TOKENS = {"g", "kg", "ml", "l", "L", "개", "매", "입", "팩"}
BRACKETS = re.compile(r"[\(\[\{（【][^\)\]\}）】]*[\)\]\}）】]")


def core_noun(name: str) -> str:
    """Last token that has no digit, unit, bracket text or brand marker (e.g. 'OO 유기농 딸기 500g' -> '딸기')."""
    text = BRACKETS.sub(" ", name)
    tokens = [t for t in re.split(r"\s+", text) if t]
    keep = []
    for t in tokens:
        if any(c.isdigit() for c in t) or t in UNIT_TOKENS or t.lower() in UNIT_TOKENS:
            continue
        if re.fullmatch(r"[A-Z0-9○]+", t) or any(m in t for m in ("®", "™")):  # brand markers: OO, CJ, ○○
            continue
        keep.append(t)
    return keep[-1] if keep else name.strip()


def apply_deal(qty: int | None, deal: str | None) -> int | None:
    if deal:
        compact = deal.replace(" ", "")
        if "1+1" in compact:
            qty = 2 * (qty or 1)
        elif "2+1" in compact:
            qty = 3 * (qty or 1)
    if qty is None:
        return None
    return min(max(qty, 1), 999)


def label_for(group: str | None, type_: str | None, attributes: list[dict], cfg: Config) -> str:
    table = cfg.label_table
    label = table["groups"].get(group, table.get("default", "clue")) if group else table.get("default", "clue")
    for rule in table.get("attribute_rules", []):
        if rule.get("group") != group:
            continue
        if "type_contains" in rule and type_ and rule["type_contains"] in type_:
            label = rule["label"]
        attr = rule.get("attribute")
        if attr and any(a["key"] == attr["key"] and a["value"] == attr["value"] for a in attributes):
            label = rule["label"]
    return label


def sensitive_hit(name: str, cfg: Config) -> bool:
    text = name.lower()
    for word in cfg.sensitive_words.get("exempt", []):
        text = text.replace(word.lower(), " ")
    return any(w.lower() in text for w in cfg.sensitive_words.get("words", []))


def postprocess(items: list[dict], cfg: Config) -> list[dict]:
    """Steps 1–6 of §7.4 plus the in-pass dedupe (before masking drops the name). Returns rows without ids.

    Same item = same product name, and the shown quantity and the order number each equal or missing on one side
    (overlapping screenshots). Same name with a different quantity is a second purchase and stays separate.
    """
    out: list[dict] = []
    for raw in items:
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        type_ = (raw.get("type") or "").strip() or core_noun(name)
        attributes = [a for a in raw.get("attributes") or [] if a.get("source") and a["source"] in name]
        row = {
            "name": name, "type": type_, "grp": raw.get("group"), "qty": apply_deal(raw.get("qty"), raw.get("deal")),
            "deal": raw.get("deal"), "order_no": raw.get("order_no"), "attributes": attributes,
            "label": label_for(raw.get("group"), type_, attributes, cfg),
            "masked": raw.get("sensitive_kind") is not None or sensitive_hit(name, cfg),
        }
        shown = raw.get("qty")
        dup = next((o for o in out if o["name"] == name and _either_missing_or_equal(o["_shown"], shown)
                    and _either_missing_or_equal(o["order_no"], row["order_no"])), None)
        if dup is not None:
            if dup["_shown"] is None and shown is not None:
                dup["_shown"], dup["qty"] = shown, row["qty"]
            for k in ("deal", "order_no"):
                if dup[k] is None and row[k] is not None:
                    dup[k] = row[k]
            continue
        out.append({**row, "_shown": shown})
    for row in out:
        row.pop("_shown")
    return out


def _either_missing_or_equal(a, b) -> bool:
    return a is None or b is None or a == b


def masked_row(row: dict) -> dict:
    """Masked: only group, qty and the flag are kept (spec §7.4 step 6)."""
    return {"name": None, "type": None, "grp": row["grp"], "qty": row["qty"], "deal": None, "order_no": None,
            "attributes": None, "label": row["label"], "masked": True}


# --------------------------------------------------------------------------------------------------------------------
# On quiet (spec §7.2)
# --------------------------------------------------------------------------------------------------------------------

def on_quiet(episode_id: str) -> None:
    """quiet_timer job. Safe to run twice; a newer capture's timer wins."""
    cfg = get_config()
    passes = 0
    while True:
        batch = _start_pass(episode_id, cfg, first=passes == 0)
        if batch is None:
            break
        passes += 1
        image_ids, paths, household_id = batch
        pictures = [image_store.load(p) for p in paths]
        rows, orders = _read(episode_id, pictures, cfg)
        _store_pass(episode_id, household_id, image_ids, rows, orders)
        for p in paths:
            image_store.delete(p)
    if passes:
        _finish(episode_id)


def _start_pass(episode_id: str, cfg: Config, first: bool) -> tuple[list[int], list[str], str] | None:
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        if ep is None or ep.status in OPEN_EXCLUDED:
            return None
        lock_household(s, ep.household_id)
        ep = s.execute(select(Episode).where(Episode.id == episode_id).with_for_update()).scalar_one()
        if first and ep.quiet_due is not None and ep.quiet_due > clock.now():
            return None
        imgs = s.execute(
            select(EpisodeImage).where(EpisodeImage.episode_id == episode_id, EpisodeImage.read.is_(False))
            .order_by(EpisodeImage.id).limit(cfg.numbers.max_images_per_call)
        ).scalars().all()
        if not imgs:
            return None
        if not ep.judged:
            ep.status = "reading"
        return [i.id for i in imgs], [i.path for i in imgs], ep.household_id


def _read(episode_id: str, pictures: list[bytes], cfg: Config) -> tuple[list[dict], list[dict]]:
    """One S1 LLM call (outside any lock). Default: no items from this pass."""
    groups = cfg.product_groups
    user = (prompts.fill(prompts.text("s1_user.txt"), N=len(pictures)) if len(pictures) > 1
            else prompts.text("s1_user_one.txt"))

    def check(raw: Any) -> list[str]:
        parsed = parse_extraction(raw, groups)
        if parsed.items or (isinstance(raw, dict) and raw.get("items") == []):
            return []
        return parsed.errors or ["읽은 물건이 하나도 형식에 맞지 않는다"]

    result = call_with_retry(
        get_llm(), stage="s1", system=prompts.system("s1"), user=user, schema=extraction_model(groups),
        retry_template=prompts.text("s1_retry.txt"), default=None, images=pictures, episode_id=episode_id,
        raw=True, check=check,
    )
    if not result.ok:
        return [], []
    parsed = parse_extraction(result.value, groups)
    return postprocess(parsed.items, cfg), parsed.orders


def _store_pass(episode_id: str, household_id: str, image_ids: list[int], rows: list[dict],
                orders: list[dict]) -> None:
    with session_scope() as s:
        lock_household(s, household_id)
        ep = s.execute(select(Episode).where(Episode.id == episode_id).with_for_update()).scalar_one()
        targets = _route_by_order_no(s, ep, rows)
        for target_id, target_rows in targets.items():
            target = ep if target_id == ep.id else s.execute(
                select(Episode).where(Episode.id == target_id).with_for_update()).scalar_one()
            _merge_items(s, target, target_rows)
            if target is not ep:
                target.rerun_pending = target.rerun_pending or target.judged
        for o in orders:
            if not any(o.values()):
                continue
            exists = o["order_no"] and s.execute(select(Order).where(
                Order.episode_id == ep.id, Order.order_no == o["order_no"])).first()
            if not exists:
                s.add(Order(episode_id=ep.id, order_no=o["order_no"], mall=o["mall"], eta_text=o["eta"]))
        for img in s.execute(select(EpisodeImage).where(EpisodeImage.id.in_(image_ids))).scalars():
            img.read = True
        ep.stage = ep.stage or "s1"
        if ep.judged and targets.get(ep.id):
            ep.rerun_pending = True


def _route_by_order_no(s: Session, ep: Episode, rows: list[dict]) -> dict[str, list[dict]]:
    """An order number that already belongs to another open episode of the household goes there (APP-07)."""
    out: dict[str, list[dict]] = {}
    owners: dict[str, str] = {}
    for row in rows:
        target = ep.id
        no = row.get("order_no")
        if no:
            if no not in owners:
                owner = s.execute(
                    select(Order.episode_id).join(Episode, Episode.id == Order.episode_id)
                    .where(Order.order_no == no, Episode.household_id == ep.household_id,
                           Episode.id != ep.id, Episode.status.not_in(OPEN_EXCLUDED))
                    .order_by(Episode.shared_at.desc()).limit(1)
                ).scalar_one_or_none()
                owners[no] = owner or ep.id
            target = owners[no]
        out.setdefault(target, []).append(row)
    return out


def _merge_items(s: Session, ep: Episode, rows: list[dict]) -> None:
    """Unmasked rows dedupe against stored items with the same rule as the pass (name, quantity, order number);
    masked rows are never merged across passes (their name is not stored)."""
    stored = s.execute(select(OrderItem).where(OrderItem.episode_id == ep.id, OrderItem.masked.is_(False))).scalars()
    seen = [(i.name, i.qty, i.order_no) for i in stored]
    for row in rows:
        if not row["masked"]:
            if any(n == row["name"] and _either_missing_or_equal(q, row["qty"])
                   and _either_missing_or_equal(o, row["order_no"]) for n, q, o in seen):
                continue
            seen.append((row["name"], row["qty"], row["order_no"]))
        data = masked_row(row) if row["masked"] else row
        s.add(OrderItem(episode_id=ep.id, id=f"it_{ep.next_item_n}", **data))
        ep.next_item_n += 1


def _finish(episode_id: str) -> None:
    run_next = False
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        lock_household(s, ep.household_id)
        ep = s.execute(select(Episode).where(Episode.id == episode_id).with_for_update()).scalar_one()
        items = s.execute(select(OrderItem).where(OrderItem.episode_id == episode_id)).scalars().all()
        if ep.judged:
            return                                    # re-run of a judged episode: spec §14 (next batch)
        if not items:
            ep.status = "read_failed"
            ep.stage = "done"
            return
        if all(i.masked for i in items):
            ep.status = "judged"
            ep.judged = True
            ep.intent = {"bundles": [], "unbundled": [], "none_reason": "all_masked", "error": None}
            ep.stage = "done"
            return
        run_next = True
    if run_next:
        runner.after_s1(episode_id)


# --------------------------------------------------------------------------------------------------------------------
# Restart (spec §2.3)
# --------------------------------------------------------------------------------------------------------------------

def recover() -> list[str]:
    """Reschedule quiet timers for every episode with unread images, at max(quiet_due, now)."""
    now = clock.now()
    with session_scope() as s:
        rows = s.execute(
            select(Episode.id, Episode.quiet_due).join(EpisodeImage, EpisodeImage.episode_id == Episode.id)
            .where(EpisodeImage.read.is_(False)).distinct()
        ).all()
    for episode_id, due in rows:
        scheduler.schedule_quiet(episode_id, max(due or now, now))
    return [r[0] for r in rows]


def household_exists(household_id: str) -> bool:
    with session_scope() as s:
        return s.get(Household, household_id) is not None
