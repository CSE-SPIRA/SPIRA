"""Read views of one episode from stored values only, no LLM (spec §12.2): `episode.json` and `rationale.json`.

Both are readable while the pipeline is still running, so a caller polling them sees each stage as it is stored:
    episode     from S1 (items)             -> item_tasks, card_ids after S5
    rationale   from S2 (evidence)          -> intents after S3 -> tasks, item_tasks after S5
Before S2 has stored its context (and no judgment ended the episode early) the rationale is `None` (route: 404).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..db.models import Card, CardLine, DeviceList, Episode, Execution, OrderItem, Task, Window
from ..pipeline.s5_cards import ActionResult, LineInput, line_state

SITUATION_KEYS = ("event", "guests", "activity", "theme")
BASIS_KEYS = ("intent",) + SITUATION_KEYS
RUN_STATUSES = {"completed", "failed", "blocked", "unknown", "unverifiable", "running"}


# ------------------------------------------------------------------------------------------------------ shared

def _items(s: Session, episode_id: str) -> list[OrderItem]:
    rows = s.execute(select(OrderItem).where(OrderItem.episode_id == episode_id)).scalars().all()
    return sorted(rows, key=lambda r: int(r.id.split("_")[1]) if r.id.split("_")[-1].isdigit() else 0)


def _runs(s: Session, episode_id: str) -> list[Execution]:
    return s.execute(select(Execution).where(Execution.plan_id == episode_id, Execution.kind == "run")
                     .order_by(Execution.at, Execution.received_at)).scalars().all()


def _task_state(task: Task, runs: list[Execution]) -> str:
    """Line state (§11.5) of a task without a card line (per-item tasks)."""
    results = [ActionResult(device=r.device or "", cmd=r.cmd or "", status=r.status, at=r.at,
                            received_at=r.received_at, operation_id=r.operation_id, reason=r.reason)
               for r in runs if r.task_id == task.task_id and r.status in RUN_STATUSES]
    state, _ = line_state(LineInput(
        task_status=task.status, rejected=task.drop_reason == "rejected",
        actions=[(a["device"], a["cmd"]) for a in task.actions], results=results))
    return state


def _shown(task: Task) -> bool:
    """Tasks dropped while judging (safety net, limits, repeats) were never sent and are not shown."""
    return task.drop_reason is None or task.drop_reason == "rejected"


def item_tasks(s: Session, episode_id: str, runs: list[Execution] | None = None) -> list[dict]:
    runs = _runs(s, episode_id) if runs is None else runs
    rows = s.execute(select(Task).where(Task.episode_id == episode_id, Task.source == "item")
                     .order_by(Task.created_at, Task.task_id)).scalars().all()
    out = []
    for t in rows:
        if not _shown(t):
            continue
        notice = next((a for a in t.actions if a.get("cmd") == "show_notice"), None)
        out.append({"task_id": t.task_id, "item": (t.meta or {}).get("item") or "",
                    "kind": (t.meta or {}).get("kind") if notice else None,
                    "text": notice.get("value") if notice else None, "state": _task_state(t, runs)})
    return out


def _cards(s: Session, episode_id: str) -> list[Card]:
    return s.execute(select(Card).where(Card.episode_id == episode_id, Card.archived.is_(False))
                     .order_by(Card.ordinal)).scalars().all()


# ----------------------------------------------------------------------------------------------------- episode

def episode_body(s: Session, ep: Episode) -> dict:
    rows = _items(s, ep.id)
    unmasked = [r for r in rows if not r.masked]
    return {
        "episode_id": ep.id, "household_id": ep.household_id, "status": ep.status,
        "shared_at": clock.iso(ep.shared_at), "item_count": len(rows), "masked_count": len(rows) - len(unmasked),
        "items": [{"item_id": r.id, "name": r.name or r.type or "", "type": r.type or "", "qty": r.qty}
                  for r in unmasked],
        "item_tasks": item_tasks(s, ep.id),
        "card_ids": [c.id for c in _cards(s, ep.id)][:2],
    }


# --------------------------------------------------------------------------------------------------- rationale

def _evidence(context: dict | None, order_types: list[str]) -> dict:
    fi = (context or {}).get("for_intent") or {}
    home = fi.get("this_home")
    kb = fi.get("kb_neighbors")
    kb_counts = None
    kb_examples: list[dict] = []
    if kb is not None:
        kb_counts = [{"intent_id": r["intent_id"], "name": r["name"], "n": r["n"]}
                     for r in kb.get("intent_counts") or [] if r.get("n", 0) >= 1]
        have = set(order_types)
        for ex in (kb.get("examples") or [])[:3]:
            shared = [i for i in ex["items"] if i in have]                # exact names, display only (R49)
            kb_examples.append({"case_id": ex["case_id"], "items": list(ex["items"]), "intent_id": ex["intent_id"],
                                "intent_text": ex.get("intent_text"),
                                "overlap": {"k": len(shared), "n": len(ex["items"]), "items": shared}})
    return {
        "calendar": list((home or {}).get("calendar") or []),
        "unusual_items": (home or {}).get("unusual_items") if home is not None else None,
        "kb_counts": kb_counts, "kb_examples": kb_examples, "kb_note": (kb or {}).get("note"),
    }


def _devices(s: Session, household_id: str) -> dict[str, dict]:
    dl = s.get(DeviceList, household_id)
    return {d["id"]: d for d in ((dl.body or {}).get("devices") or [])} if dl else {}


def rationale_body(s: Session, ep: Episode) -> dict | None:
    if ep.context is None and ep.intent is None:
        return None
    intent = ep.intent or {}
    rows = _items(s, ep.id)
    types = [r.type for r in rows if not r.masked and r.type]
    cards = _cards(s, ep.id)
    card_by_bundle = {c.bundle_index: c.id for c in cards}

    intents = []
    for n, b in enumerate(intent.get("bundles") or []):
        basis = b.get("basis") or {}
        intents.append({
            "card_id": card_by_bundle.get(n), "intent_id": b["intent_id"], "intent_text": b.get("intent_text") or "",
            "situation": {k: (b.get("situation") or {}).get(k) for k in SITUATION_KEYS},
            "basis": {k: list(basis.get(k) or []) for k in BASIS_KEYS},
            "calendar_event_id": b.get("calendar_event_id"), "calendar_tags": list(b.get("calendar_tags") or []),
        })

    devices = _devices(s, ep.household_id)
    tasks = []
    for c in cards:
        lines = s.execute(
            select(CardLine, Task).join(Task, (Task.task_id == CardLine.task_id) & (Task.episode_id == ep.id))
            .where(CardLine.card_id == c.id).order_by(CardLine.position)).all()
        for line, t in lines:
            ids = list(dict.fromkeys(a["device"] for a in t.actions))
            tasks.append({
                "task_id": t.task_id, "card_id": c.id, "line": t.line or "", "need": t.need or "", "way": t.way,
                "state": line.state,
                "devices": [{"id": d, "type": (devices.get(d) or {}).get("type", "other"),
                             "room": (devices.get(d) or {}).get("room")} for d in ids],
            })

    runs = _runs(s, ep.id)
    latest: dict[tuple[str, str], Execution] = {}
    for r in runs:                                            # ordered by at: the last final result wins
        if r.device and r.substrate and r.status in RUN_STATUSES - {"running"}:
            latest[(r.task_id, r.device)] = r
    executions = [{"task_id": r.task_id, "device": r.device, "status": r.status, "substrate": r.substrate,
                   "at": clock.iso(r.at)} for r in latest.values()]

    windows = {w.card_id: w for w in s.execute(select(Window).where(Window.episode_id == ep.id)).scalars()}
    observations = [{"card_id": c.id, "verdict": windows[c.id].verdict if c.id in windows else None,
                     "task_feedback": list((windows[c.id].task_feedback or []) if c.id in windows else [])}
                    for c in cards]

    return {
        "episode_id": ep.id, "intents": intents,
        "none_reason": None if intents else intent.get("none_reason"),
        "evidence": _evidence(ep.context, types),
        "unbundled": list(intent.get("unbundled") or []),
        "masked_count": sum(1 for r in rows if r.masked),
        "tasks": tasks, "item_tasks": item_tasks(s, ep.id, runs),
        "executions": executions, "observations": observations,
    }
