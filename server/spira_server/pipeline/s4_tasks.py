"""S4 Task generation (spec §10). Situation tasks from one LLM call; per-item tasks from item_tasks.yaml in code.

    generate(episode_id) -> S4Result        drafts in contract form (never stored; S5 confirms them)

Drafts carry what S5 needs: task_id, source, way, actions, trigger (None = held), end, need, line, target_room,
bundle index, meta. Numbers `n` of `t_{slug}#{n}` start at `episodes.next_task_n`; S5 stores the counter.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, ValidationError, create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from . import stage_times
from ..config import Config, get_config
from ..db.engine import session_scope
from ..db.models import Card, CardLine, Case, DeviceList, Episode, Household, OrderItem, Task
from ..kb.lists import KbLists, get_lists
from ..llm import prompts
from ..llm.client import call_with_retry, get_llm, pydantic_errors
from .s4_time import When, find_time, same_intent

log = logging.getLogger(__name__)

SITUATION_KEYS = ("event", "guests", "activity", "theme")
SLUG = re.compile(r"^[a-z][a-z0-9_]*$")


# ------------------------------------------------------------------------------------------------- catalog

@dataclass
class Device:
    id: str
    type: str
    room: str | None
    label: str | None
    commands: dict[str, Any]          # cmd -> value_schema (None, "text" or {param: {range|enum, default}})
    noisy: bool

    def key_type(self) -> str:
        return f"smart_plug:{self.label}" if self.type == "smart_plug" and self.label else self.type


@dataclass
class Catalog:
    devices: list[Device]
    revision: int

    def rooms(self) -> list[str]:
        return list(dict.fromkeys(d.room for d in self.devices if d.room))

    def get(self, device_id: str) -> Device | None:
        return next((d for d in self.devices if d.id == device_id), None)

    def find(self, device_type: str, cmd: str, room: str | None = None) -> list[Device]:
        return [d for d in self.devices if d.type == device_type and cmd in d.commands
                and (room is None or d.room == room)]


def catalog_from(body: dict | None) -> Catalog | None:
    """Devices with only delegated commands (`never` removed)."""
    if not body:
        return None
    devices = []
    for d in body.get("devices", []):
        never = set(d.get("never") or [])
        cmds = {c["cmd"]: c.get("value_schema") for c in d.get("commands", []) if c["cmd"] not in never}
        devices.append(Device(d["id"], d["type"], d.get("room"), d.get("label"), cmds, bool(d.get("noisy"))))
    return Catalog(devices, int(body.get("revision", 0)))


def action_key(device: Device, cmd: str) -> tuple[str, str]:
    return (device.key_type(), cmd)


# ------------------------------------------------------------------------------------------------ results

@dataclass
class Draft:
    task_id: str
    source: str                      # situation / item
    way: str                         # run / standby / notice
    actions: list[dict]
    trigger: dict | None             # None = held
    end: dict
    need: str | None = None
    line: str | None = None
    target_room: str | None = None
    bundle: int | None = None        # index into the intent bundles (situation tasks)
    end_after_start_minutes: int | None = None
    meta: dict = field(default_factory=dict)

    @property
    def held(self) -> bool:
        return self.trigger is None

    def contract(self) -> dict:
        return {"task_id": self.task_id, "source": self.source, "way": self.way, "actions": self.actions,
                "trigger": self.trigger, "end": self.end}


@dataclass
class S4Result:
    drafts: list[Draft] = field(default_factory=list)
    whens: dict[int, When | None] = field(default_factory=dict)       # bundle index -> time
    skipped_bundles: dict[int, str] = field(default_factory=dict)     # bundle index -> stopped_before / stopped_card
    dropped: list[dict] = field(default_factory=list)                 # {slug|item, reason}
    dropped_detail: dict[str, dict] = field(default_factory=dict)     # slug -> {line, way, need, actions} (display)
    next_task_n: int = 1
    llm_called: bool = False
    revision: int | None = None


# ------------------------------------------------------------------------------------------- reactions (§10.2)

@dataclass
class Reactions:
    stopped: bool = False
    off_keys: set[tuple[str, str]] = field(default_factory=set)
    off_lines: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)   # (line, keys)
    changes: list[dict] = field(default_factory=list)

    def any(self) -> bool:
        return bool(self.off_lines or self.changes)


def reactions_for(s: Session, household_id: str, episode_id: str, bundle: dict, now: datetime,
                  cfg: Config) -> Reactions:
    r = Reactions()
    if bundle["intent_id"] == "unclassified":
        return r
    tags = bundle.get("calendar_tags") or []
    rows = s.execute(select(Case).where(Case.source == "this_home", Case.household_id == household_id,
                                        Case.intent_id == bundle["intent_id"])
                     .order_by(Case.created_at.desc(), Case.case_id.desc())).scalars().all()
    rows = [x for x in rows if same_intent(bundle["intent_id"], tags, list(x.when.get("calendar_tags") or []))]
    latest = next((x for x in rows if x.verdict in ("stopped", "match")), None)
    r.stopped = latest is not None and latest.verdict == "stopped"
    cutoff = now - timedelta(days=cfg.numbers.line_off_d)
    for row in rows:
        if row.created_at and row.created_at < cutoff:
            continue
        lines = {d["task_id"]: d.get("line", "") for d in row.home_did or []}
        for fb in row.task_feedback or []:
            if fb.get("user") == "off":
                keys = [tuple(k) for k in fb.get("actions", [])]
                r.off_keys.update(keys)
                r.off_lines.append((lines.get(fb["task_id"], fb["task_id"]), keys))
    for row in rows:                                  # most recent row with changes
        changes = [c for fb in row.task_feedback or [] for c in fb.get("changes", []) or []]
        if changes:
            r.changes = changes
            break
    # lines currently unchecked on this episode's card of the same intent (re-runs)
    unchecked = s.execute(
        select(Task.actions, Task.line).join(CardLine, (CardLine.task_id == Task.task_id))
        .join(Card, Card.id == CardLine.card_id)
        .where(Card.episode_id == episode_id, Task.episode_id == episode_id, Card.intent_id == bundle["intent_id"],
               CardLine.checked.is_(False))
    ).all()
    return _add_unchecked(r, unchecked, s, household_id)


def _add_unchecked(r: Reactions, unchecked: list, s: Session, household_id: str) -> Reactions:
    if not unchecked:
        return r
    body = s.get(DeviceList, household_id)
    catalog = catalog_from(body.body if body else None)
    for actions, line in unchecked:
        keys = []
        for a in actions:
            dev = catalog.get(a["device"]) if catalog else None
            if dev:
                keys.append(action_key(dev, a["cmd"]))
        r.off_keys.update(keys)
        r.off_lines.append((line or "", keys))
    return r


def change_text(change: dict, cfg: Config) -> str:
    name = cfg.device_names.get(change["device_type"], change["device_type"])
    to = change.get("to")
    value = ", ".join(f"{k} {v}" for k, v in to.items()) if isinstance(to, dict) else str(to)
    when = f"일정 시작 {change['after_start_minutes']}분 뒤 " if change.get("after_start_minutes") is not None else ""
    return f"{when}{name}을 {change['property']}({value})로 바꿈"


# ---------------------------------------------------------------------------------------- per-item tasks (§4.3)

def _qty_kg(name: str | None) -> float:
    if not name:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", name, re.IGNORECASE)
    if m:
        return float(m.group(1))
    g = re.search(r"(\d+(?:\.\d+)?)\s*g\b", name)
    return float(g.group(1)) / 1000 if g else 0.0


def rule_matches(when: dict, item: OrderItem, bulk_rule: dict) -> bool:
    if "any" in when:
        return any(rule_matches(w, item, bulk_rule) for w in when["any"])
    if "groups" in when and item.grp not in when["groups"]:
        return False
    if "group" in when and item.grp != when["group"]:
        return False
    if "type_contains" in when and when["type_contains"] not in (item.type or ""):
        return False
    if "type_words" in when and not any(w in (item.type or "") or w in (item.name or "") for w in when["type_words"]):
        return False
    attr = when.get("attribute")
    if attr and not any(a.get("key") == attr["key"] and a.get("value") == attr["value"]
                        for a in item.attributes or []):
        return False
    if when.get("bulk") and not ((item.qty or 0) >= bulk_rule["min_qty"]
                                 or _qty_kg(item.name) >= bulk_rule["or_name_kg_at_least"]):
        return False
    return True


def _duration_of(value: Any, cfg: Config, unit: str = "min") -> str:
    """`item_tasks.yaml` durations: a numbers.yaml key (minutes) or a number of hours."""
    if isinstance(value, str):
        return clock.duration(int(cfg.numbers[value]))
    return clock.duration(int(value) * 60)


def item_end(spec: dict, cfg: Config) -> dict:
    end: dict = {"on": spec["on"]}
    if "by" in spec:
        end["by"] = spec["by"]
    if "after" in spec:
        end["after"] = _duration_of(spec["after"], cfg)
    if "or_after" in spec:
        end["or_after"] = _duration_of(spec["or_after"], cfg)
    end["restore"] = bool(spec.get("restore", False))
    return end


def default_value(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return None
    return {p: rule["default"] for p, rule in schema.items()}


def item_value(spec: dict, device: Device, item: OrderItem, cfg: Config) -> Any:
    schema = device.commands.get(spec["cmd"])
    value = spec.get("value")
    if schema is None or value is None or value == "llm_notice":
        return default_value(schema) if isinstance(schema, dict) else None
    out = default_value(schema)
    for param, wanted in value.items():
        rule = schema.get(param)
        if rule is None:
            continue
        if wanted == "from_material":
            material = next((a["value"] for a in item.attributes or [] if a.get("key") == "재질"), None)
            wanted = cfg.material_courses.get(material) if material else None
        if wanted is not None and ("enum" in rule and wanted in rule["enum"]
                                   or "range" in rule and isinstance(wanted, (int, float))
                                   and rule["range"][0] <= wanted <= rule["range"][1]):
            out[param] = wanted
    return out


def item_tasks(items: list[OrderItem], catalog: Catalog | None, cfg: Config) -> tuple[list[dict], list[OrderItem]]:
    """Per-item task specs (without ids) and the items that need a fridge notice text."""
    out: list[dict] = []
    notice_items: list[OrderItem] = []
    if catalog is None:
        return out, notice_items
    rules = cfg.item_tasks
    for spec in rules["tasks"]:
        targets = catalog.find(spec["device_type"], spec["cmd"], spec.get("room"))
        if len(targets) != 1:
            continue                                 # none or several -> skip ambiguous targets (R8)
        device = targets[0]
        for item in items:
            if item.masked or item.label != "care" or not rule_matches(spec["when"], item, rules["bulk"]):
                continue
            if spec.get("value") == "llm_notice":
                notice_items.append(item)
            out.append({"spec": spec, "device": device, "item": item, "value": item_value(spec, device, item, cfg)})
    return out, notice_items


# ------------------------------------------------------------------------------------------- message (§10.5)

def command_text(cmd: str, schema: Any) -> str:
    if schema is None:
        return cmd
    if schema == "text":
        return f"{cmd}(글자)"
    parts = []
    for p, rule in schema.items():
        if "range" in rule:
            parts.append(f"{p} {_num(rule['range'][0])}~{_num(rule['range'][1])}")
        else:
            parts.append(f"{p} {'/'.join(rule['enum'])}")
    return f"{cmd}({', '.join(parts)})"


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def _item_text(item: dict) -> str:
    qty = item.get("qty")
    text = f"{item['type']} × {qty if qty is not None else '모름'}"
    attrs = item.get("attributes") or []
    if attrs:
        text += " [" + ", ".join(f"{a['key']}: {a['value']}" for a in attrs) + "]"
    return text


def build_task_message(*, bundles: list[dict], whens: dict[int, When | None], items: list[dict],
                       notice_items: list[OrderItem], household_types: list[str], catalog: Catalog,
                       reactions: dict[int, Reactions], shared_at: datetime, cfg: Config, lists: KbLists) -> str:
    b = prompts.blocks("s4_blocks.yaml")
    unknown = b["intent"]["unknown"]
    by_type = {i["type"]: i for i in items}
    parts: list[str] = []
    for n, bundle in enumerate(bundles, start=1):
        sit = bundle["situation"]
        w = whens.get(n - 1)
        if w:
            days = (w.start.date() - shared_at.astimezone(clock.KST).date()).days
            time_text = prompts.fill(b["intent"]["time_known"], WEEKDAY=clock.weekday_ko(w.start),
                                     START=w.start.strftime("%H:%M"), END=w.end.strftime("%H:%M"), DAYS=days)
        else:
            time_text = b["intent"]["time_unknown"]
        lines = [prompts.fill(b["intent"]["header"], N=n)]
        if bundle["intent_id"] == "unclassified":
            lines.append(b["intent"]["unclassified_first_line"])
        lines.append(prompts.fill(
            b["intent"]["lines"], INTENT_ID=bundle["intent_id"], NAME=lists.intent_name(bundle["intent_id"]),
            INTENT_TEXT=bundle["intent_text"], EVENT=sit.get("event") or unknown, GUESTS=sit.get("guests") or unknown,
            ACTIVITY=sit.get("activity") or unknown, THEME=sit.get("theme") or unknown, TIME=time_text,
            ITEMS=", ".join(_item_text(by_type[t]) for t in bundle["items"] if t in by_type)))
        parts.append("\n".join(lines))
    if notice_items:
        nb = b["notice_items"]
        lines = [nb["header"]]
        for it in dict.fromkeys(notice_items):
            owner = next((k for k, bd in enumerate(bundles, start=1) if it.type in bd["items"]), None)
            lines.append(prompts.fill(nb["line"], ITEM=_item_text({"type": it.type, "qty": it.qty,
                                                                    "attributes": it.attributes}),
                                      GROUP=it.grp or unknown, BUNDLE=f" · 의도 {owner}의 물건" if owner else ""))
        parts.append("\n".join(lines))
    home = b["home"]
    lines = [home["header"]]
    if household_types:
        lines.append(prompts.fill(home["types"], TYPES=", ".join(household_types)))
    lines.append(prompts.fill(home["rooms"], ROOMS=", ".join(catalog.rooms()) or unknown))
    parts.append("\n".join(lines))
    dv = b["devices"]
    lines = [dv["header"], dv["how"]]
    for d in catalog.devices:
        cmds = ", ".join(command_text(c, sch) for c, sch in d.commands.items())
        lines.append(prompts.fill(dv["line"], ID=d.id, NAME=cfg.device_names.get(d.type, d.type),
                                  ROOM=d.room or dv["room_unknown"], COMMANDS=cmds))
    parts.append("\n".join(lines))
    rb = b["reactions"]
    for n, bundle in enumerate(bundles, start=1):
        r = reactions.get(n - 1)
        if not r or not r.any():
            continue
        lines = [rb["header"], prompts.fill(rb["how"], NAME=lists.intent_name(bundle["intent_id"]),
                                            TAGS=", ".join(bundle.get("calendar_tags") or []) or "태그 없음")]
        for line, keys in r.off_lines:
            lines.append(prompts.fill(rb["off"], LINE=line, ACTIONS=", ".join(f"{t}.{c}" for t, c in keys)))
        for change in r.changes:
            lines.append(prompts.fill(rb["changed"], CHANGE=change_text(change, cfg)))
        if r.changes:
            lines.append(rb["changed_how"])
        parts.append("\n".join(lines))
    return "\n\n".join(parts) + "\n"


# --------------------------------------------------------------------------------------------- schema (§10.6)

def _value_model(name: str, schema: Any) -> Any:
    if schema == "text":
        return str
    fields = {}
    for p, rule in schema.items():
        if "enum" in rule:
            fields[p] = (Literal[tuple(rule["enum"])], ...)  # type: ignore[valid-type]
        else:
            lo, hi = rule["range"]
            kind = int if all(float(x).is_integer() for x in (lo, hi, rule.get("default", lo))) else float
            fields[p] = (kind, Field(..., ge=lo, le=hi))
    return create_model(name, **fields)


def build_task_schema(catalog: Catalog, n_bundles: int, notice_types: list[str]) -> type[BaseModel]:
    actions = []
    for d in catalog.devices:
        for cmd, schema in d.commands.items():
            key = f"{d.id}.{cmd}"
            model_name = re.sub(r"[^A-Za-z0-9]", "_", f"A_{d.id}_{cmd}")
            fields: dict[str, Any] = {"key": (Literal[key], ...)}  # type: ignore[valid-type]
            if schema is not None:
                fields["value"] = (_value_model(model_name + "_V", schema), ...)
            actions.append(create_model(model_name, **fields))
    action_t = Annotated[Union[tuple(actions)], Field(discriminator="key")] if len(actions) > 1 else actions[0]
    rooms = catalog.rooms()
    room_t = (Literal[tuple(rooms)] | None) if rooms else None  # type: ignore[valid-type]
    bundle_t = Literal[tuple(range(1, max(n_bundles, 1) + 1))]  # type: ignore[valid-type]
    need = create_model("Need", id=(str, ...), bundle=(bundle_t, ...), need=(str, ...),
                        from_=(list[str], Field(alias="from", min_length=1)))
    trigger = create_model("Trigger", kind=(Literal["before_start", "guest_arrived", "event_end"], ...),
                           minutes=(int | None, Field(None, ge=0, le=720)))
    task = create_model(
        "Task", need_id=(str, ...), slug=(str, ...), way=(Literal["run", "standby", "notice"], ...),
        target_room=(room_t, None), actions=(list[action_t], Field(min_length=1)), trigger=(trigger | None, None),
        end_after_start_minutes=(int | None, None), line=(str, ...))
    fields: dict[str, Any] = {"needs": (list[need], ...), "tasks": (list[task], ...)}
    if notice_types:
        notice = create_model(
            "FridgeNotice", item=(Literal[tuple(dict.fromkeys(notice_types))], ...),  # type: ignore[valid-type]
            kind=(Literal["prep", "storage"] | None, None), point=(str | None, None),
            intent_change=(str | None, None), text=(str | None, None))
        fields["fridge_notices"] = (list[notice], Field(default_factory=list))
    return create_model("TaskPlan", **fields)


# ------------------------------------------------------------------------------------------- check (§10.7)

def task_errors(plan: BaseModel, bundles: list[dict]) -> list[tuple[int | None, str]]:
    """(task index or None, error). Rules of spec §10.7."""
    errs: list[tuple[int | None, str]] = []
    needs = {n.id: n for n in plan.needs}
    seen_slugs: set[str] = set()
    for i, t in enumerate(plan.tasks):
        k = i + 1
        if t.need_id not in needs:
            errs.append((i, f"할 일 {k}의 need_id \"{t.need_id}\": needs에 없다"))
        if t.way in ("standby", "notice") and t.trigger is not None:
            errs.append((i, f"할 일 {k}: {t.way}에는 trigger를 쓰지 않는다"))
        if t.way == "run" and t.trigger is None:
            errs.append((i, f"할 일 {k}: run에는 trigger가 있어야 한다"))
        if t.trigger is not None and t.trigger.kind == "before_start" and t.trigger.minutes is None:
            errs.append((i, f"할 일 {k}: before_start에는 minutes가 있어야 한다"))
        if t.way == "standby" and len({a.key.split(".")[0] for a in t.actions}) > 1:
            errs.append((i, f"할 일 {k}: standby는 기기 하나만 쓴다"))
        if t.trigger is not None and t.trigger.kind == "guest_arrived" and t.need_id in needs:
            bundle = bundles[needs[t.need_id].bundle - 1] if needs[t.need_id].bundle <= len(bundles) else None
            if bundle and not bundle["situation"].get("guests"):
                errs.append((i, f"할 일 {k}: guests가 모름인 의도에는 guest_arrived를 쓰지 않는다"))
        if t.slug in seen_slugs:
            errs.append((i, f"할 일 {k}의 slug \"{t.slug}\": 다른 할 일과 겹친다"))
        seen_slugs.add(t.slug)
    return errs


# ------------------------------------------------------------------------------------------- generate (§10.1)

@dataclass
class Prepared:
    result: S4Result
    bundles: list[dict] = field(default_factory=list)          # all bundles of the intent
    active: list[int] = field(default_factory=list)            # indexes of bundles that get situation tasks
    per_item: list[dict] = field(default_factory=list)
    notice_items: list[OrderItem] = field(default_factory=list)
    catalog: Catalog | None = None
    reactions: dict[int, Reactions] = field(default_factory=dict)   # by active position
    message: str | None = None                                  # None -> no LLM call
    schema: type[BaseModel] | None = None


def prepare(episode_id: str, *, now: datetime | None = None) -> Prepared:
    """Steps 1-7 up to the LLM call (spec §10.1): stops, times, per-item tasks, reactions, message, schema."""
    cfg, lists = get_config(), get_lists()
    now = now or clock.now()
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        household = s.get(Household, ep.household_id)
        p = Prepared(result=S4Result(next_task_n=ep.next_task_n))
        if household.paused:
            return p
        dl = s.get(DeviceList, ep.household_id)
        p.catalog = catalog_from(dl.body if dl else None)
        p.result.revision = dl.revision if dl else None
        p.bundles = (ep.intent or {}).get("bundles") or []
        items = s.execute(select(OrderItem).where(OrderItem.episode_id == episode_id, OrderItem.masked.is_(False))
                          ).scalars().all()
        items = sorted(items, key=lambda i: int(i.id.split("_")[1]))
        item_dicts = [{"type": i.type, "qty": i.qty, "attributes": i.attributes or []} for i in items]
        stopped_cards = set(s.execute(select(Card.intent_id).where(Card.episode_id == episode_id,
                                                                    Card.stopped.is_(True))).scalars())
        for idx, bundle in enumerate(p.bundles):
            if bundle["intent_id"] in stopped_cards:
                p.result.skipped_bundles[idx] = "stopped_card"
                continue
            r = reactions_for(s, ep.household_id, episode_id, bundle, now, cfg)
            if r.stopped:
                p.result.skipped_bundles[idx] = "stopped_before"
                continue
            p.reactions[len(p.active)] = r
            p.active.append(idx)
            p.result.whens[idx] = find_time(s, household_id=ep.household_id, bundle=bundle,
                                            shared_at=ep.shared_at, now=now, cfg=cfg, lists=lists)
        if p.catalog is None:
            log.warning("episode %s: no device list; no tasks", episode_id)
            return p
        p.per_item, p.notice_items = item_tasks(items, p.catalog, cfg)
        household_types = list(household.household_types or [])
        shared_at = ep.shared_at
    active_bundles = [p.bundles[i] for i in p.active]
    if not active_bundles and not p.notice_items:
        return p
    whens = {k: p.result.whens.get(i) for k, i in enumerate(p.active)}
    p.message = build_task_message(bundles=active_bundles, whens=whens, items=item_dicts,
                                   notice_items=p.notice_items, household_types=household_types,
                                   catalog=p.catalog, reactions=p.reactions, shared_at=shared_at, cfg=cfg,
                                   lists=lists)
    p.schema = build_task_schema(p.catalog, len(active_bundles), [i.type for i in p.notice_items])
    return p


def generate(episode_id: str, *, now: datetime | None = None) -> S4Result:
    """Spec §10.1 steps 1-11. Drafts are returned, never stored."""
    cfg = get_config()
    p = prepare(episode_id, now=now)
    result = p.result
    if p.catalog is None:
        return result
    active_bundles = [p.bundles[i] for i in p.active]
    if p.message is None:
        result.drafts = _number(_item_drafts(p.per_item, {}, result, cfg), [], result)
        return result
    last: dict[str, Any] = {}

    def check(raw: Any) -> list[str]:
        last["raw"] = raw
        try:
            plan = p.schema.model_validate(raw)
        except ValidationError as e:
            return pydantic_errors(e)
        return [e for _, e in task_errors(plan, active_bundles)]

    call = call_with_retry(get_llm(), stage="s4", system=prompts.system("s4"), user=p.message, schema=p.schema,
                           retry_template=prompts.text("s4_retry.txt"), default=None, episode_id=episode_id,
                           raw=True, check=check, enforce_schema=False)   # schema grows with the devices (§6.1)
    result.llm_called = True
    plan, bad = None, set()
    if call.ok:
        plan = p.schema.model_validate(call.value)
    elif "raw" in last:                         # after the retry: drop breaking tasks one by one (spec §10.7)
        plan, invalid = lenient_parse(last["raw"], p.schema)
        bad = {i for i, _ in task_errors(plan, active_bundles) if i is not None} if plan else set()
        for slug in invalid:
            result.dropped.append({"slug": slug, "reason": "schema"})
        for entry in (last["raw"].get("tasks") or []) if isinstance(last["raw"], dict) else []:
            if isinstance(entry, dict) and entry.get("slug") in invalid:
                result.dropped_detail.setdefault(entry["slug"], {
                    "line": entry.get("line"), "way": entry.get("way"), "need": None,
                    "actions": [a.get("key") for a in entry.get("actions") or [] if isinstance(a, dict)]})
    notices: dict[str, dict] = {}
    situation: list[Draft] = []
    if plan is not None:
        for i in sorted(bad):
            result.dropped.append({"slug": plan.tasks[i].slug, "reason": "format"})
            _detail(result, plan.tasks[i], plan)
        whens = {k: result.whens.get(i) for k, i in enumerate(p.active)}
        situation = _situation_drafts(plan, bad, p.active, active_bundles, whens, p.reactions, p.catalog, cfg,
                                      result)
        notices = {n.item: n.model_dump() for n in getattr(plan, "fridge_notices", []) or []}
    result.drafts = _number(_item_drafts(p.per_item, notices, result, cfg, bundles=active_bundles), situation,
                            result)
    return result


def lenient_parse(raw: Any, schema: type[BaseModel]) -> tuple[BaseModel | None, list[str]]:
    """Keep every need, task and notice that is valid on its own; returns (plan, slugs of dropped tasks)."""
    if not isinstance(raw, dict):
        return None, []
    parts: dict[str, list] = {}
    invalid: list[str] = []
    for name in ("needs", "tasks", "fridge_notices"):
        if name not in schema.model_fields:
            continue
        model = schema.model_fields[name].annotation.__args__[0]
        kept = []
        for entry in raw.get(name) or []:
            try:
                kept.append(model.model_validate(entry))
            except ValidationError:
                if name == "tasks":
                    invalid.append(entry.get("slug", "?") if isinstance(entry, dict) else "?")
        parts[name] = kept
    return schema.model_construct(**parts), invalid


def _situation_drafts(plan: BaseModel, bad: set[int], active: list[int], bundles: list[dict],
                      whens: dict[int, When | None], reactions: dict[int, Reactions], catalog: Catalog, cfg: Config,
                      result: S4Result) -> list[Draft]:
    n = cfg.numbers
    needs = {x.id: x for x in plan.needs}
    need_order = {x.id: k for k, x in enumerate(plan.needs)}
    drafts: list[tuple[int, int, Draft]] = []
    for i, t in enumerate(plan.tasks):
        if i in bad or t.need_id not in needs:
            continue
        k = needs[t.need_id].bundle - 1
        if k >= len(bundles):
            continue
        bundle = bundles[k]
        if bundle["intent_id"] == "unclassified" and t.way == "run":
            result.dropped.append({"slug": t.slug, "reason": "unclassified_run"})
            _detail(result, t, plan)
            continue
        r = reactions.get(k, Reactions())
        actions = []
        for a in t.actions:
            device_id, cmd = a.key.split(".", 1)
            dev = catalog.get(device_id)
            if dev is None or action_key(dev, cmd) in r.off_keys:
                continue
            action: dict[str, Any] = {"device": device_id, "cmd": cmd}
            if getattr(a, "value", None) is not None:
                v = a.value
                action["value"] = v if isinstance(v, str) else v.model_dump()
            actions.append(action)
        if not actions:
            result.dropped.append({"slug": t.slug, "reason": "switched_off"})
            _detail(result, t, plan)
            continue
        w = whens.get(k)
        trigger, end = _trigger_end(t, actions, w, catalog, n, cfg)
        drafts.append((k, need_order[t.need_id], Draft(
            task_id=_slug(t.slug), source="situation", way=t.way, actions=actions, trigger=trigger, end=end,
            need=needs[t.need_id].need, line=t.line, target_room=t.target_room, bundle=active[k],
            end_after_start_minutes=t.end_after_start_minutes, meta={"slug": _slug(t.slug)})))
    drafts.sort(key=lambda x: (x[0], x[1]))
    out: list[Draft] = []
    per_bundle: dict[int, int] = {}
    for k, _, d in drafts:
        per_bundle[k] = per_bundle.get(k, 0) + 1
        if per_bundle[k] > n.max_lines:
            result.dropped.append({"slug": d.task_id, "reason": "max_lines"})
            result.dropped_detail[d.task_id] = {"line": d.line, "way": d.way, "need": d.need,
                                                "actions": [f"{a['device']}.{a['cmd']}" for a in d.actions]}
            continue
        out.append(d)
    return out


def _detail(result: S4Result, t: BaseModel, plan: BaseModel) -> None:
    """Keep what a task dropped inside S4 said, for display (the drop list keeps only slug and reason)."""
    need = next((x.need for x in getattr(plan, "needs", []) or [] if x.id == getattr(t, "need_id", None)), None)
    result.dropped_detail[t.slug] = {"line": getattr(t, "line", None), "way": getattr(t, "way", None), "need": need,
                                     "actions": [getattr(a, "key", None) for a in getattr(t, "actions", []) or []]}


def store_result(episode_id: str, result: S4Result) -> None:
    """Store what S4 produced when it ends (`episodes.s4`, stage time `s4`), before S5 confirms it: display and
    replay only. S5 still gets the drafts in memory and confirms from them (spec §2.4)."""
    record = {
        "llm_called": result.llm_called,
        "whens": {str(k): ({"start": clock.iso(w.start), "end": clock.iso(w.end), "source": w.source} if w else None)
                  for k, w in result.whens.items()},
        "skipped_bundles": {str(k): v for k, v in result.skipped_bundles.items()},
        "drafts": [{**d.contract(), "need": d.need, "line": d.line, "target_room": d.target_room, "bundle": d.bundle,
                    "meta": {k: v for k, v in d.meta.items() if k in ("item", "kind", "slug")}} for d in result.drafts],
        "dropped": [{**x, **result.dropped_detail.get(x.get("slug") or "", {})} for x in result.dropped],
    }
    with session_scope() as s:
        ep = s.execute(select(Episode).where(Episode.id == episode_id).with_for_update()).scalar_one_or_none()
        if ep is None:
            return
        ep.s4 = record
        stage_times.mark(ep, "s4")


def _slug(slug: str) -> str:
    s = slug.strip().lower().replace("-", "_").replace(" ", "_")
    return s if SLUG.match(s) else "task"


def _trigger_end(t: BaseModel, actions: list[dict], w: When | None, catalog: Catalog, n, cfg: Config
                 ) -> tuple[dict | None, dict]:
    if t.way == "notice":
        fridge = next(x for x in cfg.item_tasks["tasks"] if x["name"] == "fridge")
        return {"event": "package.brought_in", "released": False}, item_end(fridge["end"], cfg)
    if t.way == "standby":
        dev = catalog.get(actions[0]["device"])
        end: dict = {"on": f"{dev.type}.started", "by": "user"}
        if w:
            end["or_time"] = clock.iso(w.end)
            return {"time": clock.iso(w.start)}, {**end, "restore": False}
        end["or_after"] = clock.duration(n.standby_max_min)
        return {"event": "package.brought_in", "released": False}, {**end, "restore": False}
    # run
    cleaner_only = all(catalog.get(a["device"]).type == "cleaner" for a in actions)
    if w is None:
        return None, {"on": "event_end", "restore": not cleaner_only}       # held: filled when a time is found
    kind = t.trigger.kind
    if kind == "before_start":
        minutes = n.before_start_default_min if cfg.demo else t.trigger.minutes
        trigger: dict = {"time": clock.iso(w.start - timedelta(minutes=minutes))}
    elif kind == "guest_arrived":
        trigger = {"event": "guest_arrived", "first_only": True,
                   "window": {"from": clock.iso(w.start - timedelta(minutes=n.guest_window_before_min)),
                              "to": clock.iso(w.end)}}
    else:
        trigger = {"event": "event_end", "first_only": True,
                   "window": {"from": clock.iso(w.start),
                              "to": clock.iso(w.end + timedelta(minutes=n.end_fallback_min))}}
        return trigger, {"on": "event_end", "after": f"{n.after_event_end_min}m", "restore": True}
    if t.end_after_start_minutes is not None:
        return trigger, {"time": clock.iso(w.start + timedelta(minutes=t.end_after_start_minutes)), "restore": True}
    return trigger, {"on": "event_end", "or_time": clock.iso(w.end + timedelta(minutes=n.end_fallback_min)),
                     "restore": not cleaner_only}


def public_words(bundles: list[dict], lists: KbLists) -> set[str]:
    words: set[str] = set()
    for b in bundles:
        words.add(b.get("intent_text") or "")
        words.add(lists.intent_name(b["intent_id"]))
        for key in ("event", "guests", "theme"):
            if b["situation"].get(key):
                words.add(b["situation"][key])
        words.update(b.get("calendar_tags") or [])
    return {w for w in words if w}


def _item_drafts(per_item: list[dict], notices: dict[str, dict], result: S4Result, cfg: Config,
                 bundles: list[dict] | None = None) -> list[Draft]:
    lists = get_lists()
    banned = public_words(bundles or [], lists)
    out = []
    for p in per_item:
        spec, device, item = p["spec"], p["device"], p["item"]
        action: dict[str, Any] = {"device": device.id, "cmd": spec["cmd"]}
        meta: dict[str, Any] = {"item": item.type, "item_id": item.id, "rule": spec["name"]}
        if spec.get("value") == "llm_notice":
            notice = notices.get(item.type) or {}
            text = (notice.get("text") or "").strip()
            if not text:
                continue                                       # no text -> no task
            hit = next((w for w in banned if w in text), None)
            if hit:
                result.dropped.append({"item": item.type, "reason": "public_text", "word": hit})
                continue
            action["value"] = text
            meta.update(kind=notice.get("kind"), point=notice.get("point"), intent_change=notice.get("intent_change"))
        elif p["value"] is not None:
            action["value"] = p["value"]
        out.append(Draft(task_id=spec["name"], source="item", way=spec["way"], actions=[action],
                         trigger={"event": "package.brought_in", "released": False},
                         end=item_end(spec["end"], cfg), meta=meta))
    return out


def _number(item_drafts: list[Draft], situation: list[Draft], result: S4Result) -> list[Draft]:
    """t_{slug}#{n}: situation tasks by bundle then needs order, then per-item tasks (spec §10.4)."""
    n = result.next_task_n
    used: set[str] = set()
    out = []
    for d in situation + item_drafts:
        slug = d.task_id
        if d.source == "situation":
            base, k = slug, 2
            while slug in used:
                slug, k = f"{base}_{k}", k + 1
            used.add(slug)
        d.task_id = f"t_{slug}#{n}"
        n += 1
        out.append(d)
    result.next_task_n = n
    return out
