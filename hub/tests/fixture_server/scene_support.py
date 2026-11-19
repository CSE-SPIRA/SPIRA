"""Opt-in, non-inference test support for the live h_042 scene runner."""

from datetime import datetime, timedelta, timezone
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from spira_contracts.card import Card
from spira_contracts.plan import Plan

from .replay import CONTRACTS, Replay


class NextOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    episode_id: Literal["ep_9031", "ep_9150"]
    starts_in_seconds: int = Field(default=65, ge=1, le=3600)
    duration_seconds: int = Field(default=30, ge=1, le=3600)


def live_replay(order: NextOrder, *, demo_mode: bool, now: datetime | None = None):
    now = now if now is not None else datetime.now(timezone.utc)
    replay = Replay(order.episode_id)
    numbers_path = CONTRACTS.parent / "server/config/numbers.yaml"
    numbers = yaml.safe_load(numbers_path.read_text(encoding="utf-8"))
    if demo_mode:
        numbers.update(numbers["demo"])

    # Translate committed schedule landmarks throughout the plan/card templates.
    # The upload publishes the first snapshot. Later live revisions use wall time.
    timestamps = {
        replay.plan.sent_at: now,
        replay.episode.shared_at: now,
    }
    if replay.card:
        starts = now + timedelta(seconds=order.starts_in_seconds)
        ends = starts + timedelta(seconds=order.duration_seconds)
        tasks = {task["task_id"]: task for task in replay.files["plan.v1.json"]["tasks"]}
        clean = tasks["t_clean#1"]
        guest = tasks["t_mood#3"]["trigger"]["window"]
        opens = starts - timedelta(minutes=numbers["guest_window_before_min"])
        timestamps.update(
            {
                replay.card.starts_at: starts,
                clean["trigger"]["time"]: starts
                - timedelta(minutes=numbers["before_start_default_min"]),
                guest["from"]: opens,
                guest["to"]: ends,
                clean["end"]["or_time"]: ends
                + timedelta(minutes=numbers["end_fallback_min"]),
            }
        )

    def rebase(value):
        if isinstance(value, dict):
            return {key: rebase(entry) for key, entry in value.items()}
        if isinstance(value, list):
            return [rebase(entry) for entry in value]
        if isinstance(value, str) and value in timestamps:
            return timestamps[value].isoformat()
        return value

    for name, body in replay.files.items():
        if name.startswith(("plan.v", "card.")):
            replay.files[name] = rebase(body)
            if name.startswith("plan.v"):
                replay.files[name]["sent_at"] = now.isoformat()
                for task in replay.files[name]["tasks"]:
                    if task["end"].get("on") == "fridge.door_opened":
                        task["end"]["after"] = f"{numbers['notice_after_door_min']}m"
    replay.live = True
    replay.clock = now
    replay.plan = replay.load(Plan, "plan.v1.json")
    replay.card = replay.load(Card, "card.v1.json")
    replay.episode = replay.episode.model_copy(update={"shared_at": now.isoformat()})
    return replay
