"""Publish the committed scene templates on story time."""

from datetime import datetime, timedelta
from random import Random
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict
from spira_contracts.calendar import Calendar
from spira_contracts.card import Card
from spira_contracts.plan import Plan

from .replay import CONTRACTS, JudgmentStage, Replay
from .story_clock import StoryClock


class NextOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    episode_id: Literal["ep_9031", "ep_9150", "ep_9120"]


def server_numbers():
    return yaml.safe_load((CONTRACTS.parent / "server/config/numbers.yaml").read_text(encoding="utf-8"))


# Fixture processing gaps in story seconds. The quiet-window presets can
# insert a wait between S1 and S2 without changing these gaps.
STAGE_GAPS = {
    JudgmentStage.READING: 1,
    JudgmentStage.ITEMS: 3,
    JudgmentStage.EVIDENCE: 2,
    JudgmentStage.INTENTS: 3,
    JudgmentStage.TASKS: 3,
    JudgmentStage.PUBLISHED: 3,
}


def stage_offsets():
    offsets = {}
    elapsed = 0
    for stage, gap in STAGE_GAPS.items():
        if stage == JudgmentStage.EVIDENCE:
            elapsed = 0  # Later offsets are relative to the end of the quiet window.
        elapsed += gap
        offsets[stage] = elapsed
    return offsets


def realistic_schedule(seed, sequence):
    rng = Random(f"{seed}:{sequence}")
    quiet = server_numbers()["quiet_s"]
    offsets = stage_offsets()
    previous = 0
    for stage, seconds in offsets.items():
        if stage == JudgmentStage.EVIDENCE:
            previous = 0
        offsets[stage] = previous = max(previous, seconds + rng.randint(-4, 8))
    if rng.randrange(4):
        first, second = rng.choice([
            (JudgmentStage.EVIDENCE, JudgmentStage.INTENTS),
            (JudgmentStage.INTENTS, JudgmentStage.TASKS),
            (JudgmentStage.TASKS, JudgmentStage.PUBLISHED),
        ])
        offsets[second] = offsets[first]
    return quiet, offsets


def judgment_times(shared_at, quiet_seconds, offsets):
    quiet_end = shared_at + timedelta(seconds=quiet_seconds)
    return quiet_end, {
        stage: (shared_at if stage < JudgmentStage.EVIDENCE else quiet_end) + timedelta(seconds=seconds)
        for stage, seconds in offsets.items()
    }


def schedule_publication(replay):
    ready_at = replay.judgment_at[JudgmentStage.PUBLISHED].isoformat()
    replay.set_plan(replay.plan.model_copy(update={"sent_at": ready_at}))
    if replay.card:
        replay.card = replay.card.model_copy(update={"updated_at": ready_at})


def substitute(value, replacements: dict[str, str]):
    if isinstance(value, dict):
        return {key: substitute(entry, replacements) for key, entry in value.items()}
    if isinstance(value, list):
        return [substitute(entry, replacements) for entry in value]
    return replacements.get(value, value) if isinstance(value, str) else value


def live_replay(order: NextOrder, *, clock: StoryClock, sequence: int = 1, pace=None):
    replay = Replay(order.episode_id)
    if sequence > 1:
        identifiers = {order.episode_id: f"{order.episode_id}{sequence}"}
        if replay.card:
            card_id = replay.card.card_id
            identifiers[card_id] = f"{card_id}{sequence}"

        replay.files = substitute(replay.files, identifiers)
        replay.episode = replay.episode.model_copy(update={
            "episode_id": identifiers[order.episode_id],
            "card_ids": [identifiers[card_id] for card_id in replay.episode.card_ids],
        })
    shared_at = datetime.fromisoformat(replay.episode.shared_at)
    offsets = stage_offsets()
    quiet_seconds, offsets = pace or (offsets[JudgmentStage.ITEMS], offsets)
    replay.capture_quiet_seconds = quiet_seconds
    replay.quiet_end, replay.judgment_at = judgment_times(shared_at, quiet_seconds, offsets)
    replay.live = True
    replay.story_clock = clock
    replay.clock = replay.judgment_at[JudgmentStage.PUBLISHED]
    replay.plan = replay.load(Plan, "plan.v1.json")
    schedule_publication(replay)
    if replay.card:
        card = replay.load(Card, "card.v1.json") or replay.load(Card, "card.held.json")
        summary = card.summary.model_copy(update={"waiting_for": replay.waiting_for(card.lines)})
        replay.card = card.model_copy(update={"updated_at": replay.plan.sent_at, "summary": summary})
        replay.prepare_observation()
    return replay


def apply_scene_calendar(replay: Replay, calendar: Calendar):
    if calendar == replay.calendar and replay.published():
        replay.find_calendar_time()
        replay.prepare_observation()
