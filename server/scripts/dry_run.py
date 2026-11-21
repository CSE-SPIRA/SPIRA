"""Dry run: one folder of order screenshots -> S1..S5 on the local server DB, no hub (handoff §6, step 5/6).

    cd server
    python scripts/dry_run.py --images orders/01_birthday --home dev/home.yaml --kb off
    python scripts/dry_run.py --images orders/01_birthday --home dev/home.yaml --kb on --now 2026-11-20T21:00:00+09:00

Reads server/.env (real LLM, EMBED_MODE=bge, local DATABASE_URL). Writes out/<folder>/:
    s1_items.json  s2_context.json  s3_message.txt  s3_intent.json  s4_tasks.json  plan.json  card.json
    llm_calls.jsonl  llm_io.jsonl  checks.txt
With --kb on also kb_search.tsv (every searched case: sim, bonus, used rank, items, an empty ox column for marking
"really similar?") and kb_sweep.txt (the same search summarised again with other floors, caps and KB_SAMPLE sizes).
The folder may hold answer.txt ("물건 · 수량" per line, "?" for an unknown quantity, " · 가림" for an item that must be
masked, lines starting with "제외:" are notes). Exit code 0 when every check passed.

Options: --split posts each image as its own share (grouping), --resend posts the same share again (source_id).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


# ------------------------------------------------------------------------------------------------ helpers

@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def parse_answer(text: str) -> list[dict]:
    """'딸기 · 2', '컵케이크 믹스 · ?', '감기약 · 1 · 가림', '제외: ...' (note)."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("제외:") or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.replace("·", "|").split("|")]
        qty = parts[1] if len(parts) > 1 else "?"
        out.append({"name": parts[0], "qty": None if qty in ("?", "") else int(qty),
                    "masked": len(parts) > 2 and parts[2] == "가림"})
    return out


def compare_answer(answer: list[dict], items: list[dict]) -> list[Check]:
    checks = []
    unmasked = [i for i in items if not i["masked"]]
    used: set[int] = set()
    for a in answer:
        if a["masked"]:
            continue
        hit = next((k for k, i in enumerate(unmasked) if k not in used and
                    (a["name"] in (i["name"] or "") or a["name"] in (i["type"] or "")
                     or (i["type"] or "") in a["name"])), None)
        if hit is None:
            checks.append(Check(f"answer: {a['name']}", False, "not read"))
            continue
        used.add(hit)
        got = unmasked[hit]
        ok = a["qty"] is None or got["qty"] == a["qty"]
        checks.append(Check(f"answer: {a['name']}", ok, f"read as {got['type']} × {got['qty']}"))
    extra = [i["type"] for k, i in enumerate(unmasked) if k not in used]
    checks.append(Check("answer: no extra items", not extra, ", ".join(extra)))
    n_masked = sum(1 for a in answer if a["masked"])
    if n_masked:
        got = sum(1 for i in items if i["masked"])
        checks.append(Check("answer: masked items", got >= n_masked, f"{got} masked, {n_masked} expected"))
    return checks


class RecordingProvider:
    """Wraps the LLM provider and keeps every call's input and output (llm_io.jsonl)."""

    def __init__(self, inner) -> None:
        self.inner, self.name, self.model = inner, inner.name, inner.model
        self.log: list[dict] = []

    def complete(self, **kw):
        started = time.monotonic()
        entry = {"stage": kw["stage"], "enforce_schema": kw.get("enforce_schema", True),
                 "system_chars": len(kw["system"]), "user": kw["user"],
                 "images": len(kw["images"])}
        try:
            reply = self.inner.complete(**kw)
        except Exception as e:  # noqa: BLE001
            entry.update(error=repr(e), seconds=round(time.monotonic() - started, 2))
            self.log.append(entry)
            raise
        entry.update(output=reply.data, text=reply.text, refusal=reply.refusal, input_tokens=reply.input_tokens,
                     output_tokens=reply.output_tokens, seconds=round(time.monotonic() - started, 2))
        self.log.append(entry)
        return reply


class RecordingSearch:
    """Wraps s2_context.search and keeps the query vector, arguments and cases of every KB search."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.calls: list[dict] = []

    def __call__(self, engine, q, **kw):
        entry: dict = {"q": q, "kw": kw}
        self.calls.append(entry)
        try:
            entry["cases"] = self.inner(engine, q, **kw)
        except Exception as e:  # noqa: BLE001
            entry["error"] = repr(e)
            raise
        return entry["cases"]


def dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- run

def run(images_dir: Path, home_path: Path, kb: str, now: datetime | None, out_dir: Path | None,
        split: bool = False, resend: bool = False) -> int:
    os.environ["KB_MODE"] = kb
    from spira_server.settings import get_settings as _settings

    _settings.cache_clear()
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from spira_server import clock
    from spira_server.config import get_config
    from spira_server.db.engine import session_scope
    from spira_server.db.models import Card, Episode, EpisodeImage, LlmCall, Order, OrderItem, Plan, Task
    from spira_server.dev.seed import HomeError, load_home, seed
    from spira_server.kb import embedding
    from spira_server.llm import client as llm_client
    from spira_server.main import create_app
    from spira_server.pipeline import s1_extract, s2_context
    from spira_server.pipeline.s3_intent import build_intent_message, item_dicts
    from spira_server.pipeline.s5_cards import card_body
    from spira_server.pipeline.s5_plan import command_allowed
    from spira_server.settings import get_settings

    settings = get_settings()
    cfg = get_config()
    pictures = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not pictures:
        print(f"no jpg/png in {images_dir}", file=sys.stderr)
        return 2
    out = out_dir or SERVER / "out" / images_dir.name
    out.mkdir(parents=True, exist_ok=True)

    _migrate()
    with session_scope() as s:                       # only this run's LLM calls go to llm_calls.jsonl and the checks
        first_call_id = (s.execute(select(func.max(LlmCall.id))).scalar() or 0) + 1
    llm = llm_client.get_llm()
    recorder = RecordingProvider(llm.provider)
    llm.provider = recorder
    kb_recorder = RecordingSearch(s2_context.search)
    s2_context.search = kb_recorder
    run_clock = clock.MovableClock(now or clock.now())
    clock.set_now(run_clock)

    print(f"[dry run] {images_dir.name}: {len(pictures)} image(s), KB_MODE={kb}, now={clock.iso(run_clock.at)}, "
          f"LLM={settings.llm_provider}/{settings.llm_model}, EMBED_MODE={settings.embed_mode}")
    print("[1/4] embedding model ...", flush=True)
    embedding.warm_up()
    if not embedding.ready():
        print("embedding model failed to load", file=sys.stderr)
        return 2

    print("[2/4] home ...", flush=True)
    try:
        home = load_home(home_path, run_clock.at)
    except HomeError as e:
        print(f"home.yaml: {e}", file=sys.stderr)
        return 2
    seeded = seed(home, run_clock.at)
    print(f"      {seeded}")

    print("[3/4] POST /v1/orders ...", flush=True)
    app = create_app(start_background=False)
    http = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.app_demo_token}"}
    blobs = [p.read_bytes() for p in pictures]
    source = hashlib.sha256(b"".join(blobs)).hexdigest()[:16]
    shares = [[b] for b in blobs] if split else [blobs[i:i + 3] for i in range(0, len(blobs), 3)]
    responses = []
    for k, share in enumerate(shares):
        files = [("images", (f"{k}_{j}.png", b, "image/png")) for j, b in enumerate(share)]
        r = http.post("/v1/orders", data={"household_id": home.household_id, "source_id": f"{source}-{k}",
                                          "shared_at": clock.iso(run_clock.at)}, files=files, headers=headers)
        responses.append({"status": r.status_code, "body": r.json()})
        run_clock.advance(seconds=20)
    if resend:
        files = [("images", (f"0_{j}.png", b, "image/png")) for j, b in enumerate(shares[0])]
        r = http.post("/v1/orders", data={"household_id": home.household_id, "source_id": f"{source}-0"},
                      files=files, headers=headers)
        responses.append({"status": r.status_code, "body": r.json(), "resend": True})
    episode_id = responses[0]["body"].get("episode_id")
    if not episode_id:
        print(f"order upload failed: {responses}", file=sys.stderr)
        return 1

    print("[4/4] S1..S5 ...", flush=True)
    run_clock.advance(seconds=cfg.numbers.quiet_s + 1)
    error = None
    try:
        s1_extract.on_quiet(episode_id)
    except Exception as e:  # noqa: BLE001
        error = repr(e)
        print(f"pipeline error: {error}", file=sys.stderr)

    # ---------------------------------------------------------------------------------------------- outputs
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        rows = sorted(s.execute(select(OrderItem).where(OrderItem.episode_id == episode_id)).scalars(),
                      key=lambda i: int(i.id.split("_")[1]))
        items = [{"id": i.id, "name": i.name, "type": i.type, "group": i.grp, "qty": i.qty, "deal": i.deal,
                  "label": i.label, "attributes": i.attributes, "masked": i.masked, "order_no": i.order_no}
                 for i in rows]
        orders = [{"order_no": o.order_no, "mall": o.mall, "eta": o.eta_text}
                  for o in s.execute(select(Order).where(Order.episode_id == episode_id)).scalars()]
        dump(out / "s1_items.json", {"episode_id": episode_id, "status": ep.status, "stage": ep.stage,
                                     "uploads": responses, "orders": orders, "items": items})
        dump(out / "s2_context.json", ep.context)
        message = ""
        if ep.context:
            message = build_intent_message(ep.context, item_dicts([r for r in rows if not r.masked]))
        (out / "s3_message.txt").write_text(message, encoding="utf-8")
        intent = dict(ep.intent or {})
        s4_info = intent.pop("s4", None)
        dump(out / "s3_intent.json", intent or None)
        tasks = s.execute(select(Task).where(Task.episode_id == episode_id)).scalars().all()
        dump(out / "s4_tasks.json", {
            "tasks": [{"task_id": t.task_id, "status": t.status, "drop_reason": t.drop_reason, "source": t.source,
                       "way": t.way, "need": t.need, "line": t.line, "target_room": t.target_room,
                       "actions": t.actions, "trigger": t.trigger, "end": t.end, "meta": t.meta}
                      for t in sorted(tasks, key=lambda t: int(t.task_id.rsplit("#", 1)[1]))],
            "s4": s4_info})
        plan = s.get(Plan, (episode_id, ep.plan_version)) if ep.plan_version else None
        dump(out / "plan.json", plan.body if plan else None)
        cards = [card_body(s, c, run_clock.at) for c in s.execute(select(Card).where(Card.episode_id == episode_id)
                                                                  .order_by(Card.ordinal)).scalars()]
        dump(out / "card.json", cards)
        calls = s.execute(select(LlmCall).where(LlmCall.id >= first_call_id).order_by(LlmCall.id)).scalars().all()
        (out / "llm_calls.jsonl").write_text("".join(json.dumps(
            {"stage": c.stage, "episode_id": c.episode_id, "provider": c.provider, "model": c.model,
             "input_tokens": c.input_tokens, "output_tokens": c.output_tokens, "latency_ms": c.latency_ms,
             "attempts": c.attempts, "outcome": c.outcome}, ensure_ascii=False) + "\n" for c in calls),
            encoding="utf-8")
        (out / "llm_io.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False, default=str) + "\n"
                                                  for x in recorder.log), encoding="utf-8")
        image_paths = [i.path for i in s.execute(select(EpisodeImage).where(
            EpisodeImage.episode_id == episode_id)).scalars()]

        # ---------------------------------------------------------------------------------------- checks
        finished = error is None and ep.stage == "done"
        checks: list[Check] = [Check("pipeline finished", finished,
                                     f"status={ep.status} stage={ep.stage} {error or ''}".strip())]
        failed_calls = [f"{c.stage}: {c.outcome}" for c in calls if c.outcome != "ok"]
        checks.append(Check("every LLM call answered in format", not failed_calls, ", ".join(failed_calls)))
        s3_error = (intent.get("error") or {}).get("stage") == "s3"
        checks.append(Check("S3 judged without a format failure", not s3_error,
                            "; ".join((intent.get("error") or {}).get("errors", [])) if s3_error else ""))
        if resend:
            last = responses[-1]
            checks.append(Check("resend: same episode, 200", last["status"] == 200
                                and last["body"].get("episode_id") == episode_id, json.dumps(last["body"])))
        checks += _contract_checks(plan.body if plan else None, cards)
        if plan:
            bad = [f"{t['task_id']}:{a['cmd']}" for t in plan.body["tasks"] for a in t["actions"]
                   if not command_allowed(t["way"], a["cmd"], cfg.command_policy)]
            checks.append(Check("commands inside the allow list", not bad, ", ".join(bad)))
            checks += _time_checks(plan.body, clock)
        numbers = sorted(int(t.task_id.rsplit("#", 1)[1]) for t in tasks)
        checks.append(Check("task numbers 1..n over the order", numbers == list(range(1, len(numbers) + 1)),
                            str(numbers)))
        words = [w for w in cfg.sensitive_words.get("words", []) if w in message]
        checks.append(Check("no sensitive word in the S3 message", not words, ", ".join(words)))
        if kb == "on":
            types = list(dict.fromkeys(i["type"] for i in items if not i["masked"]))
            checks.append(kb_outputs(out, kb_recorder, ep, types, settings, cfg))
        left = [p for p in image_paths if Path(p).exists()]
        checks.append(Check("images deleted", not left, ", ".join(left)))
        answer_file = images_dir / "answer.txt"
        if answer_file.exists():
            answer = parse_answer(answer_file.read_text(encoding="utf-8"))
            masked_names = [a["name"] for a in answer if a["masked"]]
            leaked = [n for n in masked_names if n in message]
            checks.append(Check("masked answer items absent from the S3 message", not leaked, ", ".join(leaked)))
            checks += compare_answer(answer, items)
        else:
            checks.append(Check("answer.txt", True, "not given: S1 not compared"))

    tokens = sum((x.get("input_tokens") or 0) + (x.get("output_tokens") or 0) for x in recorder.log)
    passed = all(c.ok for c in checks)
    lines = [f"{'PASS' if passed else 'FAIL'} {sum(c.ok for c in checks)}/{len(checks)}  episode {episode_id}  "
             f"status {ep.status}  intents {[b['intent_id'] for b in intent.get('bundles', [])]}  "
             f"LLM calls {len(recorder.log)}  tokens {tokens}", ""]
    lines += [f"[{'ok' if c.ok else 'FAIL'}] {c.name}" + (f" — {c.detail}" if c.detail else "") for c in checks]
    (out / "checks.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {out}")
    llm.provider = recorder.inner
    s2_context.search = kb_recorder.inner
    clock.set_now(None)
    return 0 if passed else 1


# ------------------------------------------------------------------------------------------- KB search (§8.3)

FLOORS = (0.5, 0.55, 0.6, 0.65, 0.7)
CAPS = (20, 30, 50, 100, 200)
SAMPLES = (0.25, 0.5)
TSV_COLUMNS = ["rank", "case_id", "sim", "cal_bonus", "house_bonus", "score", "above_floor", "used_rank", "rep",
               "intent_id", "items", "intent_text", "situation", "calendar_tags", "household_types", "ox"]


def kb_outputs(out: Path, rec: RecordingSearch, ep, types: list[str], settings, cfg) -> Check:
    """kb_search.tsv + kb_sweep.txt from the search S2 made; the check fails when S2 did not get KB cases."""
    if ep.error and ep.error.get("stage") == "s2":
        return Check("S2 KB searched", False, ep.error.get("message", ""))
    done = [c for c in rec.calls if "cases" in c]
    if not done:
        return Check("S2 KB searched", False, "no KB search (pipeline stopped before S2?)")
    call = done[-1]
    cases = call["cases"]
    n = cfg.numbers
    this_home = ((ep.context or {}).get("for_intent") or {}).get("this_home")
    home = settings.home_context == "on" and this_home is not None
    calendar = this_home["calendar"] if home else []
    house = this_home["household_types"] if home else []
    nb = ((ep.context or {}).get("for_intent") or {}).get("kb_neighbors") or {}
    reps = {e["case_id"] for e in nb.get("examples", [])}
    write_kb_tsv(out / "kb_search.tsv", cases, calendar, house, home, n, reps)
    lines = sweep_lines(cases, types, calendar, house, home, n, settings, call)
    (out / "kb_sweep.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    above = sum(1 for c in cases if c.sim > n.sim_floor)
    top = f"{cases[0].sim:.3f}" if cases else "-"
    return Check("S2 KB searched", True, f"{len(cases)} cases, {above} above {n.sim_floor}, "
                 f"used {nb.get('similar_count', 0)}, top sim {top}" + (f", {nb['note']}" if nb.get("note") else ""))


def write_kb_tsv(path: Path, cases, calendar, house, home, n, reps: set[str]) -> None:
    from spira_server.pipeline.s2_context import context_bonus, rank_similar

    used, _ = rank_similar(cases, calendar, house, home=home, n=n, sim_floor=n.sim_floor, max_use=n.max_use)
    used_rank = {c.case_id: k for k, c in enumerate(used, start=1)}
    cal_tags = {t for e in calendar for t in e["tags"]}
    rows = ["\t".join(TSV_COLUMNS)]
    for k, c in enumerate(cases, start=1):
        cal, hh = context_bonus(c, cal_tags, set(house), home, n)
        cells = [k, c.case_id, f"{c.sim:.4f}", f"{cal:g}", f"{hh:g}", f"{c.sim + cal + hh:.4f}",
                 "y" if c.sim > n.sim_floor else "", used_rank.get(c.case_id, ""), "y" if c.case_id in reps else "",
                 c.intent_id, ", ".join(sorted(c.items)), c.intent_text or "",
                 json.dumps({k2: v for k2, v in (c.situation or {}).items() if v}, ensure_ascii=False),
                 ", ".join(c.when.get("calendar_tags") or []), ", ".join(c.household.get("types") or []), ""]
        rows.append("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in cells))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _sim_at(sims: list[float], k: int) -> str:
    return f"{sims[k - 1]:.3f}" if len(sims) >= k else "-"


def _intents(cases) -> str:
    from collections import Counter

    return " · ".join(f"{i} {m}" for i, m in Counter(c.intent_id for c in cases).most_common()) or "-"


def _summary(cases, types, calendar, house, home, n, floor: float, cap: int) -> str:
    from spira_server.kb.lists import get_lists
    from spira_server.pipeline.s2_context import summarize_neighbors

    block, _ = summarize_neighbors(cases, types, calendar, house, home=home, n=n, lists=get_lists(),
                                   sim_floor=floor, max_use=cap)
    above = sum(1 for c in cases if c.sim > floor)
    if block.get("note"):
        return f"floor {floor:.2f} cap {cap:>3}: above {above:>3} -> KB not given ({block['note']})"
    counts = " · ".join(f"{x['intent_id']} {x['n']}" for x in block["intent_counts"])
    reps = ", ".join(e["intent_id"] for e in block["examples"])
    return (f"floor {floor:.2f} cap {cap:>3}: above {above:>3}, used {block['similar_count']:>3} | {counts} "
            f"| reps {reps}")


def _used_band(cases, calendar, house, home, n) -> tuple[str, int, list]:
    """(sim range of the used cases, how many are in only because of the bonus, those cases)."""
    from spira_server.pipeline.s2_context import rank_similar

    used, _ = rank_similar(cases, calendar, house, home=home, n=n, sim_floor=n.sim_floor, max_use=n.max_use)
    if not used:
        return "-", 0, []
    by_sim = {c.case_id for c in sorted((c for c in cases if c.sim > n.sim_floor),
                                        key=lambda c: (c.sim, c.case_id), reverse=True)[: n.max_use]}
    moved = [c for c in used if c.case_id not in by_sim]
    sims = [c.sim for c in used]
    return f"{max(sims):.3f} ~ {min(sims):.3f} (band {max(sims) - min(sims):.3f})", len(moved), moved


def sweep_lines(cases, types, calendar, house, home, n, settings, call) -> list[str]:
    import statistics

    from spira_server.db.engine import kb_engine
    from spira_server.kb.search import search as kb_search
    from spira_server.pipeline.s2_context import context_bonus

    kw = call["kw"]
    sims = [c.sim for c in cases]
    above = sum(1 for s in sims if s > n.sim_floor)
    lines = [f"KB search: KB_VERSION={settings.kb_version} KB_SAMPLE={kw.get('sample')} limit {kw.get('limit')} "
             f"returned {len(cases)} | now: sim_floor {n.sim_floor}, max_use {n.max_use}, min_similar "
             f"{n.min_similar}, w_cal {n.w_cal}, w_house {n.w_house}, HOME_CONTEXT {'on' if home else 'off'}",
             f"basket: {', '.join(types)}", ""]
    if not cases:
        return lines + ["no cases returned"]
    lines.append("sim by rank: " + "  ".join(f"#{k} {_sim_at(sims, k)}" for k in (1, 10, 20, 50, 100, 150, 200))
                 + f"  median {statistics.median(sims):.3f}")
    full = above == len(cases) == kw.get("limit")
    lines.append(f"above floor {n.sim_floor}: {above} of {len(cases)}"
                 + ("  <- every returned case is above the floor: the search limit cut, not the floor" if full else ""))
    band, moved_n, moved = _used_band(cases, calendar, house, home, n)
    cal_tags = {t for e in calendar for t in e["tags"]}
    bonus = [context_bonus(c, cal_tags, set(house), home, n) for c in cases if c.sim > n.sim_floor]
    lines.append(f"used {min(above, n.max_use)}: sim {band}; above floor with calendar bonus "
                 f"{sum(1 for b in bonus if b[0])}, household bonus {sum(1 for b in bonus if b[1])}")
    lines.append(f"in the used set only because of the bonus: {moved_n}" + (f" ({_intents(moved)})" if moved else ""))
    best: dict[str, float] = {}
    count: dict[str, int] = {}
    for c in cases:
        best.setdefault(c.intent_id, c.sim)
        count[c.intent_id] = count.get(c.intent_id, 0) + (c.sim > n.sim_floor)
    lines.append("best sim per intent (n above floor): " + " · ".join(
        f"{i} {s:.3f} ({count[i]})" for i, s in sorted(best.items(), key=lambda x: -x[1])[:8]))
    lines += ["", "[floor x cap] the same searched cases, other numbers (S3 saw only the current one)"]
    for floor in FLOORS:
        for cap in CAPS:
            mark = "  <- now" if (floor == n.sim_floor and cap == n.max_use) else ""
            lines.append(_summary(cases, types, calendar, house, home, n, floor, cap) + mark)
    lines += ["", f"[KB size] KB_SAMPLE fractions of the same KB, floor {n.sim_floor} cap {n.max_use}"]
    if kw.get("sample", 1.0) < 1.0:
        return lines + [f"skipped: this run already searched KB_SAMPLE={kw.get('sample')}"]
    for sample in SAMPLES + (1.0,):
        if sample == 1.0:
            part = cases
        else:
            try:
                part = kb_search(kb_engine(), call["q"], **{**kw, "sample": sample})
            except Exception as e:  # noqa: BLE001
                lines.append(f"sample {sample}: error {e!r}")
                continue
        ps = [c.sim for c in part]
        p_above = sum(1 for s in ps if s > n.sim_floor)
        p_band, p_moved, _ = _used_band(part, calendar, house, home, n)
        lines.append(f"sample {sample:<4}: returned {len(part):>3}, above {p_above:>3}, sim #1 {_sim_at(ps, 1)} "
                     f"#50 {_sim_at(ps, 50)} #200 {_sim_at(ps, 200)}, used sim {p_band}, moved by bonus {p_moved} | "
                     + _summary(part, types, calendar, house, home, n, n.sim_floor, n.max_use).split(": ", 1)[1])
    return lines


def _contract_checks(plan: dict | None, cards: list[dict]) -> list[Check]:
    from jsonschema import ValidationError
    from spira_contracts.validate import validate

    out = []
    for name, doc, schema in [("plan.json schema", plan, "plan.json")] + [
            (f"card {c['card_id']} schema", c, "card.json") for c in cards]:
        if doc is None:
            continue
        try:
            validate(doc, schema)
            out.append(Check(name, True))
        except ValidationError as e:
            out.append(Check(name, False, e.message))
    return out


def _time_checks(plan: dict, clock) -> list[Check]:
    sent = clock.parse(plan["sent_at"])
    bad = []
    for t in plan["tasks"]:
        trig, end = t["trigger"], t["end"]
        start = clock.parse(trig["time"]) if "time" in trig else (
            clock.parse(trig["window"]["from"]) if trig.get("window") else None)
        if start is not None and "time" in trig and start <= sent:
            bad.append(f"{t['task_id']} starts at or before sent_at")
        stop = end.get("time") or end.get("or_time")
        if start is not None and stop and clock.parse(stop) <= start:
            bad.append(f"{t['task_id']} ends before it starts")
    return [Check("times after now, end after start", not bad, "; ".join(bad))]


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(SERVER / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER / "migrations"))
    command.upgrade(cfg, "head")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--images", required=True, type=Path, help="folder with 1-n order screenshots (+ answer.txt)")
    p.add_argument("--home", required=True, type=Path, help="fake home yaml (dev/home.example.yaml)")
    p.add_argument("--kb", choices=["on", "off"], default="off")
    p.add_argument("--now", help="ISO 8601 with offset; default: the real time")
    p.add_argument("--out", type=Path, help="output folder; default out/<images folder name>")
    p.add_argument("--split", action="store_true", help="post each image as its own share")
    p.add_argument("--resend", action="store_true", help="post the first share again with the same source_id")
    a = p.parse_args(argv)
    from spira_server import clock

    now = clock.parse(a.now) if a.now else None
    return run(a.images, a.home, a.kb, now, a.out, a.split, a.resend)


if __name__ == "__main__":
    raise SystemExit(main())

