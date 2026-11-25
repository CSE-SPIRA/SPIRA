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


JUDGMENT_SECONDS = {
    JudgmentStage.READING: 1,     # Assumed start after share, no Server measurement.
    JudgmentStage.ITEMS: 6,       # Assumed read completion after share, no Server measurement.
    JudgmentStage.EVIDENCE: 15,   # Assumed S2 offset after quiet end, no Server measurement.
    JudgmentStage.INTENTS: 30,    # Assumed S3 offset after quiet end, no Server measurement.
    JudgmentStage.TASKS: 45,      # Assumed S4 offset after quiet end, no Server measurement.
    JudgmentStage.PUBLISHED: 60,  # Assumed S5 offset after quiet end, no Server measurement.
}


def realistic_schedule(seed, sequence):
    rng = Random(f"{seed}:{sequence}")
    quiet = server_numbers()["quiet_s"]
    offsets = {stage: max(0, seconds + rng.randint(-4, 8)) for stage, seconds in JUDGMENT_SECONDS.items()}
    offsets[JudgmentStage.ITEMS] = max(offsets[JudgmentStage.READING], offsets[JudgmentStage.ITEMS])
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
    quiet_seconds, offsets = pace or (server_numbers()["quiet_s"], JUDGMENT_SECONDS)
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
