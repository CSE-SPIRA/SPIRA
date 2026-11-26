"""Build clock stops from the live plan and the recorded world events."""

from datetime import datetime

from spira_contracts.plan import EventTrigger, TimeTrigger

from .observation import SEOUL
from .replay import Replay

QUIET_END = "judgment.quiet_end"

TIME_LABELS = {
    "clean": "청소",
    "safe": "안전 모드",
    "oven": "오븐 대기",
}
EVENT_LABELS = {
    "package.brought_in": "택배 들이기",
    "guest_arrived": "손님 도착",
    "light.changed": "엄마가 조명을 바꿈",
    "event_end": "파티 끝",
}


def plan_moments(replay: Replay):
    moments_by_time = {}
    line_labels = {line.task_id: line.text for line in replay.card.lines} if replay.card else {}
    for task in replay.plan.tasks:
        trigger = task.trigger
        if isinstance(trigger, TimeTrigger):
            at = trigger.time
            action = task.task_id.split("#")[0].removeprefix("t_")
            label = TIME_LABELS.get(action, line_labels.get(task.task_id, task.task_id))
        elif isinstance(trigger, EventTrigger) and trigger.event == "guest_arrived" and trigger.window:
            at, label = trigger.window.from_, "손님 맞이"
        else:
            continue
        at = datetime.fromisoformat(at).astimezone(SEOUL).isoformat()
        moment = moments_by_time.setdefault(at, {
            "id": f"time:{task.task_id}", "at": at, "kind": "time",
            "label": label, "task_ids": [], "event": None,
        })
        if moment["task_ids"]:
            moment["label"] += f" · {label}"
        moment["task_ids"].append(task.task_id)

    events = [
        {
            "id": event["event_id"], "at": event["at"], "kind": "event",
            "label": EVENT_LABELS[event["type"]], "task_ids": [], "event": event["type"],
        }
        for event in replay.files.get("events.json", [])
        if event["type"] in EVENT_LABELS
        and (event["type"] != "light.changed" or event["payload"].get("by") == "user")
    ]
    moments = [*moments_by_time.values(), *events]
    if replay.quiet_end:
        moments.append({
            "id": f"time:{QUIET_END}", "at": replay.quiet_end.isoformat(), "kind": "time",
            "label": "같은 주문을 기다리는 시간 끝", "task_ids": [], "event": QUIET_END,
            "episode_id": replay.episode.episode_id,
        })
    return sorted(moments, key=lambda moment: datetime.fromisoformat(moment["at"]))
