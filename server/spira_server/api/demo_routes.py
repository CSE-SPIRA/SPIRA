"""Demo route (contracts/openapi/demo.yaml, spec §12.5): stage states and times of one judgment for the presenter
screen. Only with DEMO_MODE=1; otherwise every path here answers 404 as if it did not exist."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..db.engine import session_scope
from ..db.models import Episode, LlmCall
from ..pipeline.stage_times import wall
from ..settings import get_settings
from .auth import require_app
from .errors import ApiError

router = APIRouter(dependencies=[Depends(require_app)])

STAGES = ("s1", "s2", "s3", "s4", "s5")
LLM_STAGES = ("s1", "s3", "s4")


def _demo_only() -> None:
    if not get_settings().demo_mode:
        raise ApiError("not_found", "Not found.")


def _llm(s: Session, episode_id: str) -> dict[str, dict]:
    rows = s.execute(
        select(LlmCall.stage, func.count(), func.coalesce(func.sum(LlmCall.latency_ms), 0),
               func.coalesce(func.sum(LlmCall.input_tokens), 0), func.coalesce(func.sum(LlmCall.output_tokens), 0))
        .where(LlmCall.episode_id == episode_id, LlmCall.stage.in_(LLM_STAGES)).group_by(LlmCall.stage)).all()
    return {st: {"calls": int(n), "ms": int(ms), "input_tokens": int(i), "output_tokens": int(o)}
            for st, n, ms, i, o in rows}


def _failed_stage(ep: Episode) -> str | None:
    """Where the episode stopped early: s1 read nothing / every item masked ends after s1; s2 KB down."""
    if ep.status == "read_failed":
        return "s1"
    if (ep.error or {}).get("stage") == "s2":
        return "s2"
    return None


def trace_body(s: Session, ep: Episode, at: float | None, now: datetime | None = None) -> dict:
    times = ep.stage_times or {}
    start = clock.parse(times["received"]) if "received" in times else None
    elapsed = at if at is not None else ((now or wall()) - start).total_seconds() if start else None

    def offset(key: str) -> float | None:
        return round((clock.parse(times[key]) - start).total_seconds(), 3) if start and key in times else None

    failed = _failed_stage(ep)
    masked_only = ep.status == "judged" and (ep.intent or {}).get("none_reason") == "all_masked" and "s2" not in times
    llm = _llm(s, ep.id)
    stages, stopped, running_given = [], False, False
    for name in STAGES:
        done_s = offset(name)
        ended = name in times if start is None else done_s is not None and (at is None or done_s <= at)
        if start is None and name not in times:                     # stored before stage times: from the status
            ended = ep.stage == "done" or (ep.stage == "s2" and name in ("s1", "s2"))
        if stopped:
            state = "skipped"
        elif ended:
            state = "failed" if name == failed else "done"
            stopped = name == failed or (masked_only and name == "s1")
        else:
            s1_start = offset("s1_start")
            started = name != "s1" or (s1_start is not None and (at is None or s1_start <= at)) or start is None
            moving = at is not None or ep.stage != "done"
            state = "running" if started and moving and not running_given else "pending"
            running_given = True                                     # only the first unfinished stage can run
        stages.append({"name": name, "state": state,
                       "done_s": done_s if state in ("done", "failed") else None,
                       "llm": llm.get(name) if state == "done" and name in LLM_STAGES else None})
    return {
        "episode_id": ep.id, "status": ep.status, "mode": "live" if at is None else "replay", "at": at,
        "started_at": times.get("received"), "elapsed_s": round(elapsed, 3) if elapsed is not None else None,
        "finished": all(x["state"] in ("done", "failed", "skipped") for x in stages), "stages": stages,
    }


@router.get("/v1/demo/episodes/{episode_id}/trace", dependencies=[Depends(_demo_only)])
def get_trace(episode_id: str = Path(pattern=r"^ep_[0-9A-Za-z_]+$"),
              at: float | None = Query(None, ge=0)) -> dict:
    with session_scope() as s:
        ep = s.get(Episode, episode_id)
        if ep is None:
            raise ApiError("not_found", "Unknown episode.")
        return trace_body(s, ep, at)
