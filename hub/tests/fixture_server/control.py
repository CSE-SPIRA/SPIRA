"""Fixture-only rehearsal state and judgment controls."""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field

from .catalogue import CASES, DERIVED_FIELDS, STAGE_NAMES
from .control_transport import ControlInput
from .observation import SEOUL
from .replay import JudgmentStage, wire
from .scene_support import JUDGMENT_SECONDS, judgment_times, schedule_publication, server_numbers

SECONDS = Annotated[int, Field(ge=0, le=86_400)]
STAGES = {stage.name.lower(): stage for stage in JUDGMENT_SECONDS}
HOLD_STAGE = Literal["received", "reading", "items", "quiet_window", "evidence", "intents", "tasks", "published"]


class EpisodeAction(ControlInput):
    action: Literal["select", "share", "repeat", "capture", "reset", "calendar", "resume"]
    episode_id: Literal["ep_9031", "ep_9150", "ep_9120"] | None = None


class CaseAction(ControlInput):
    id: str | None


class ClockAction(ControlInput):
    action: Literal["set", "advance", "next", "pause", "resume", "rate"]
    at: str | None = None
    moment: str | None = None
    over_seconds: float = Field(default=6, ge=1, le=60)
    rate: float | None = Field(default=None, ge=1, le=600)


class Realistic(ControlInput):
    seed: int | None


class Pace(ControlInput):
    preset: Literal["server", "fast", "slow", "custom", "stuck", "release"]
    scope: Literal["current", "next"] = "next"
    quiet_seconds: SECONDS | None = None
    offsets: dict[str, SECONDS] | None = None
    hold: HOLD_STAGE | None = None

    def schedule(self):
        quiet = server_numbers()["quiet_s"]
        offsets = JUDGMENT_SECONDS.copy()
        if self.preset == "fast":
            quiet = 12
            offsets = {stage: index for index, stage in enumerate(offsets, 1)}
        if self.preset == "slow":
            quiet *= 4
            offsets = {stage: seconds * 4 for stage, seconds in offsets.items()}
        if self.quiet_seconds is not None:
            quiet = self.quiet_seconds
        for name, seconds in (self.offsets or {}).items():
            if name not in STAGES:
                raise ValueError(f"Unknown judgment stage: {name}")
            offsets[STAGES[name]] = seconds
        read_stages = [offsets[stage] for stage in offsets if stage < JudgmentStage.EVIDENCE]
        judgment_stages = [offsets[stage] for stage in offsets if stage >= JudgmentStage.EVIDENCE]
        if read_stages != sorted(read_stages) or judgment_stages != sorted(judgment_stages) or read_stages[-1] > quiet:
            raise ValueError("Offsets must be in stage order and reading must finish by quiet end")
        if self.preset == "stuck" and not self.hold:
            raise ValueError("Select the stage to hold")
        if self.preset == "release" and self.scope != "current":
            raise ValueError("Release requires a current episode")
        return quiet, offsets


def hold_before(hold):
    return "reading" if hold == "received" else hold


def stages(replay, now=None):
    if not replay or not replay.judgment_at:
        return []
    now = now or replay.now()
    stage = replay.judgment(now)
    terminal = replay.read_failure and stage >= JudgmentStage.ITEMS
    held = replay.judgment_hold
    times = {"received": datetime.fromisoformat(replay.episode.shared_at)}
    times.update({name: replay.judgment_at[step] for name, step in STAGES.items()})
    times["quiet_window"] = replay.quiet_end
    done = {name: stage >= step for name, step in STAGES.items()}
    done["received"] = True
    done["quiet_window"] = (
        stage >= JudgmentStage.EVIDENCE or (
            stage >= JudgmentStage.ITEMS and now >= replay.quiet_end and held != "quiet_window" and not terminal
        )
    )
    return [
        {
            "id": name, "label": label, "at": times[name].isoformat(), "done": done[name],
            "held": held == name and not done[name], "unreachable": terminal and not done[name],
        }
        for name, label in STAGE_NAMES.items()
    ]


def retime(replay, pace, schedule):
    now = replay.now()
    prior = {stage["id"]: stage for stage in stages(replay)}
    hold = hold_before(pace.hold)
    if hold and prior[hold]["done"]:
        raise ValueError("This judgment stage has already passed")
    if pace.preset == "stuck" and pace.offsets is None and pace.quiet_seconds is None:
        replay.judgment_hold = hold
        return
    quiet_end, proposed = judgment_times(datetime.fromisoformat(replay.episode.shared_at), *schedule)
    if pace.preset == "release":
        quiet_end = now
        proposed = dict.fromkeys(proposed, now)
    if not prior["quiet_window"]["done"]:
        read_end = replay.judgment_at[JudgmentStage.ITEMS] if prior["items"]["done"] else proposed[JudgmentStage.ITEMS]
        replay.quiet_end = max(now, quiet_end, read_end)
        replay.capture_quiet_seconds = schedule[0]
    cursor = now
    for name, stage in STAGES.items():
        if prior[name]["done"]:
            continue
        if stage == JudgmentStage.EVIDENCE:
            cursor = max(cursor, replay.quiet_end)
        cursor = max(cursor, proposed[stage])
        replay.judgment_at[stage] = cursor
    replay.judgment_hold = hold
    schedule_publication(replay)


def extend_quiet_window(replay):
    now = replay.now()
    prior_end = replay.quiet_end
    base = getattr(replay, "capture_quiet_seconds", server_numbers()["quiet_s"])
    replay.quiet_end = max(prior_end, now + timedelta(seconds=base))
    for stage in JUDGMENT_SECONDS:
        if stage >= JudgmentStage.EVIDENCE:
            replay.judgment_at[stage] += replay.quiet_end - prior_end
    schedule_publication(replay)


def derive_plan(replay, case_id):
    field, value = DERIVED_FIELDS[case_id]
    task_id = "t_oven#4"
    tasks = []
    for task in replay.plan.tasks:
        if task.task_id == task_id:
            replay.derived_tasks[task_id] = task
            action = task.actions[0]
            key = field.split(".")[1]
            if key == "value":
                value = {**action.value, "temp_c": value}
            changed = type(action).model_validate({**wire(action), key: value})
            task = task.model_copy(update={"actions": [changed]})
        tasks.append(task)
    replay.set_plan(replay.plan.model_copy(update={"tasks": tasks}))


class Rehearsal:
    def __init__(self):
        self.active_case = None
        self.next_pace = None
        self.share_mode = None
        self.capture_episode = None
        self.derive_next = None
        self.resend_version = None
        self.sample_source = None
        self.sample_serial = 0
        self.sample_response = None
        self.pulls = {}
        self.acked_at = {}

    def record_pull(self, plans):
        at = datetime.now(SEOUL).isoformat()
        for plan in plans:
            key = plan.plan_id, plan.plan_version
            info = self.pulls.get(key, {"pulled_at": at, "count": 0})
            self.pulls[key] = {**info, "last_pulled_at": at, "count": info["count"] + 1}

    def versions(self, snapshots, now):
        rows = []
        for replay in snapshots:
            if not replay.published(now):
                continue
            for version, plan in replay.plans.items():
                key = plan.plan_id, version
                ack = replay.acks.get(version)
                rejected = {item.task_id: item.reason for item in ack.rejected_tasks} if ack else {}
                rows.append({
                    "episode_id": plan.plan_id, "version": version, "published_at": plan.sent_at,
                    **self.pulls.get(key, {"pulled_at": None, "last_pulled_at": None, "count": 0}),
                    "acked_at": self.acked_at.get(key), "ack": wire(ack) if ack else None,
                    "tasks": [
                        {"task_id": task.task_id, "status": (
                            "rejected" if task.task_id in rejected or (ack and ack.status == "rejected")
                            else "accepted" if ack else "pending"
                        ), "reason": rejected.get(task.task_id)}
                        for task in plan.tasks
                    ],
                    "cancelled": [wire(entry) for entry in plan.cancelled],
                })
        return rows

    def catalogue(self, household):
        return [case.entry(household) for case in CASES]
