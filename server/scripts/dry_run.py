"""Dry run: one folder of order screenshots -> S1..S5 on the local server DB, no hub (handoff §6, step 5/6).

    cd server
    python scripts/dry_run.py --images orders/01_birthday --home dev/home.yaml --kb off
    python scripts/dry_run.py --images orders/01_birthday --home dev/home.yaml --kb on --now 2026-11-20T21:00:00+09:00

Reads server/.env (real LLM, EMBED_MODE=bge, local DATABASE_URL). Writes out/<folder>/:
    s1_items.json  s2_context.json  s3_message.txt  s3_intent.json  s4_tasks.json  plan.json  card.json
    llm_calls.jsonl  llm_io.jsonl  checks.txt
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
from datetime import datetime, timedelta
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
        entry = {"stage": kw["stage"], "system_chars": len(kw["system"]), "user": kw["user"],
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


def dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- run

def run(images_dir: Path, home_path: Path, kb: str, now: datetime | None, out_dir: Path | None,
        split: bool = False, resend: bool = False) -> int:
    os.environ["KB_MODE"] = kb
    from spira_server.settings import get_settings as _settings

    _settings.cache_clear()
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from spira_server import clock
    from spira_server.config import get_config
    from spira_server.db.engine import session_scope
    from spira_server.db.models import Card, Episode, EpisodeImage, LlmCall, Order, OrderItem, Plan, Task
    from spira_server.dev.seed import HomeError, load_home, seed
    from spira_server.kb import embedding
    from spira_server.llm import client as llm_client
    from spira_server.main import create_app
    from spira_server.pipeline import s1_extract
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
    llm = llm_client.get_llm()
    recorder = RecordingProvider(llm.provider)
    llm.provider = recorder
    run_clock = clock.MovableClock(now or clock.now())
    clock.set_now(run_clock)
    started_at = run_clock.at

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
        calls = s.execute(select(LlmCall).where(LlmCall.created_at >= started_at - timedelta(hours=1))
                          .order_by(LlmCall.id)).scalars().all()
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
    clock.set_now(None)
    return 0 if passed else 1


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

