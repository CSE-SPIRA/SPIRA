"""Close a live card's S7 window from the Hub receipts in this rehearsal."""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from spira_contracts.case_row import Change, Feedback
from spira_contracts.common import By, HomeEvent, OffWhen, RestoreItemStatus, TaskFeedback, Verdict, Way
from spira_contracts.devices import Devices
from spira_contracts.event import Event
from spira_contracts.execution_result import RestoreResult
from spira_contracts.memory import ChangedItem, Episode, Intent, OffLine
from spira_contracts.plan import EventTrigger
from spira_contracts.rationale import Observation, Rationale

if TYPE_CHECKING:
    from .replay import Replay

SEOUL = ZoneInfo("Asia/Seoul")


@dataclass
class ObservationWindow:
    scheduled_start: datetime | None = None
    end_due: datetime | None = None
    guest_lead: timedelta = timedelta()
    closed_at: datetime | None = None

    def links_home_event(self, at: datetime):
        return self.scheduled_start is not None and (
            self.scheduled_start - self.guest_lead <= at <= (self.closed_at or self.end_due)
        )


def close_observation(replay: "Replay", events: list[Event], windows: list[ObservationWindow], now: datetime):
    card, window = replay.card, replay.observation_window
    if card is None or replay.observation is not None:
        return None
    if card.stopped and all(line.end_state is not None or not replay.started(line.task_id) for line in card.lines):
        closed_at = now
    elif window.scheduled_start is not None:
        closed_at = next((
            at for event in events
            if event.type == HomeEvent.EVENT_END and event.source == "hub"
            and window.scheduled_start <= (at := datetime.fromisoformat(event.at)) <= window.end_due
        ), window.end_due if now >= window.end_due else None)
        if closed_at is None:
            return None
    else:
        return None

    tasks = {task.task_id: task for plan in replay.plans.values() for task in plan.tasks}
    templates = {
        task.task_id.split("#")[0]: task for plan in replay.card_templates() for task in plan.tasks
    }
    line_tasks = [tasks.get(line.task_id) or templates[line.task_id.split("#")[0]] for line in card.lines]
    starts = {line.task_id: replay.started_at(line.task_id, by=closed_at) for line in card.lines}
    start_at = min((at for at in starts.values() if at is not None), default=window.scheduled_start or closed_at)
    devices = {
        device.id: device for inventory in (replay.load(Devices, "devices.json"), replay.devices)
        if inventory is not None for device in inventory.devices
    }
    feedback = []
    signalled = False
    for line, task in zip(card.lines, line_tasks, strict=True):
        action_devices = {action.device: devices[action.device] for action in task.actions}
        actions = []
        for action in task.actions:
            device = action_devices[action.device]
            key = f"smart_plug:{device.label}" if device.type == "smart_plug" and device.label else device.type
            actions.append((key, action.cmd))
        if not line.checked:
            switched_at = replay.checked_changed_at.get(line.task_id, closed_at)
            ran = starts[line.task_id] is not None and starts[line.task_id] <= switched_at
            feedback.append(Feedback(
                task_id=line.task_id, actions=actions, user=TaskFeedback.OFF,
                when=OffWhen.DURING_RUN if ran else OffWhen.BEFORE_RUN,
                at=switched_at.astimezone(SEOUL).date().isoformat(),
            ))
            continue

        changes = []
        for event in events:
            at = datetime.fromisoformat(event.at)
            if at > closed_at or sum(other.links_home_event(at) for other in windows) > 1:
                continue
            if event.source == "hub" and window.links_home_event(at):
                if task.way == Way.RUN and isinstance(task.trigger, EventTrigger) and event.type == task.trigger.event:
                    signalled = True
                continue
            device = action_devices.get(event.source)
            if device is None or at < start_at or event.payload.by != By.USER:
                continue
            if task.way == Way.STANDBY and event.type == f"{device.type}.started":
                signalled = True
            ran_at = starts[line.task_id]
            if ran_at is not None and ran_at < at and event.type == f"{device.type}.changed":
                changes.append(Change(
                    device_type=device.type, property=event.payload.property, to=event.payload.to,
                    after_start_minutes=int((at - (window.scheduled_start or start_at)).total_seconds() / 60),
                ))

        # A restore skip confirms a change but supplies no property, value or change time.
        restore_skipped = starts[line.task_id] is not None and any(
            isinstance(packet := result.root, RestoreResult) and packet.task_id == line.task_id
            and any(item.device in action_devices and item.status == RestoreItemStatus.SKIPPED_USER_CHANGED
                    for item in packet.items)
            for result in replay.results.values()
        )
        details = {"changes": changes} if changes or restore_skipped else {}
        feedback.append(Feedback(
            task_id=line.task_id, actions=actions,
            user=TaskFeedback.CHANGED if details else TaskFeedback.KEPT, **details,
        ))

    verdict = Verdict.MATCH if signalled else Verdict.UNCONFIRMED
    if card.stopped:
        verdict = Verdict.STOPPED
    replay.observation = Observation(card_id=card.card_id, verdict=verdict, task_feedback=feedback)
    window.closed_at = closed_at
    return start_at


def record_memory(replay: "Replay", start_at: datetime, intent_names: dict[str, str], off_days: int):
    card, observation = replay.card, replay.observation
    if not card.lines or card.intent_id == "unclassified":
        return
    rationale = replay.load(Rationale, "rationale.json")
    calendar_tags = next((intent.calendar_tags for intent in rationale.intents
                          if intent.card_id == card.card_id), []) if rationale else []
    case_id = f"home_{replay.household_id}_{card.episode_id}_1"
    episode = Episode(case_id=case_id, date=start_at.astimezone(SEOUL).date().isoformat(), verdict=observation.verdict)
    off_lines, changed = [], []
    for line, feedback in zip(card.lines, observation.task_feedback, strict=True):
        if feedback.user == TaskFeedback.OFF:
            until = date.fromisoformat(feedback.at) + timedelta(days=off_days)
            off_lines.append(OffLine(line=line.text, until=until.isoformat(), case_id=case_id))
        for change in feedback.changes or ():
            value = change.to
            if isinstance(value, dict) and value.keys() == {"kelvin"}:
                description = f"색온도를 {value['kelvin']} K로 바꿈"
            else:
                description = f"{change.property} 값을 {json.dumps(value, ensure_ascii=False)}(으)로 바꿈"
            minutes = change.after_start_minutes
            relative = "뒤" if minutes >= 0 else "전"
            changed.append(ChangedItem(
                device_type=change.device_type, case_id=case_id,
                change=f"일정 시작 {abs(minutes)}분 {relative} {description}",
            ))
    replay.memory.intents.append(Intent(
        intent_id=card.intent_id, name=intent_names.get(card.intent_id, card.intent_id),
        calendar_tags=calendar_tags, episodes=[episode], off_lines=off_lines, changed=changed, habit_time=None,
    ))
