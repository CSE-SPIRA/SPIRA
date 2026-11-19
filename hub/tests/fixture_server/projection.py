"""Project the fixture's C-3 and C-4 evidence using the C-7 state mapping."""

from datetime import datetime, timedelta

from spira_contracts.common import (
    By, EndState, ExecutionStatus, HomeEvent, LineState, RestoreItemStatus,
)
from spira_contracts.event import Event
from spira_contracts.execution_result import RestoreResult, RunResult
from spira_contracts.plan import EventTrigger, Task, TimeTrigger

at_time = datetime.fromisoformat


def action_results(task: Task, runs: list[RunResult]) -> list[RunResult]:
    latest = {}
    terminal = set()
    for result in sorted(runs, key=lambda result: at_time(result.at)):
        action = (result.device, result.cmd)
        operation = (action, result.operation_id)
        if result.status != ExecutionStatus.RUNNING:
            terminal.add(operation)
        elif operation in terminal:
            continue
        latest[action] = result
    return [
        latest[key] for action in task.actions
        if (key := (action.device, action.cmd)) in latest
    ]


def run_state(task: Task, latest: list[RunResult], rejected: bool, previous: LineState):
    if rejected:
        return LineState.FAILED, None
    statuses = [result.status for result in latest]
    completed = statuses.count(ExecutionStatus.COMPLETED)
    all_final = len(statuses) == len(task.actions) and ExecutionStatus.RUNNING not in statuses
    if not all_final:
        if completed or ExecutionStatus.RUNNING in statuses or previous == LineState.RUNNING:
            return LineState.RUNNING, None
        return LineState.SCHEDULED, None
    if completed:
        return (LineState.DONE if completed == len(task.actions) else LineState.PARTIAL), None
    if ExecutionStatus.FAILED in statuses:
        return LineState.FAILED, None
    for result in latest:
        if result.status == ExecutionStatus.BLOCKED:
            return LineState.BLOCKED, result.reason.value
    return LineState.UNKNOWN, None


def matching_trigger(trigger: EventTrigger, events: list[Event], admitted_at: datetime):
    if trigger.released is False:
        return None
    if trigger.at is not None:
        return at_time(trigger.at)
    for event in events:
        if event.type != trigger.event or event.source != "hub":
            continue
        at = at_time(event.at)
        if at >= admitted_at and (
            trigger.window is None
            or at_time(trigger.window.from_) <= at <= at_time(trigger.window.to)
        ):
            return at
    return None


def duration(value: str | None):
    if value is None:
        return timedelta()
    count = int(value[:-1])
    return timedelta(minutes=count) if value.endswith("m") else timedelta(hours=count)


def task_end(task: Task, events: list[Event], admitted_at: datetime):
    end, trigger = task.end, task.trigger
    triggered = (
        at_time(trigger.time) if isinstance(trigger, TimeTrigger)
        else matching_trigger(trigger, events, admitted_at)
    )
    absolute = end.time or end.or_time
    deadline = at_time(absolute) if absolute else None
    if end.or_after and triggered is not None:
        relative = triggered + duration(end.or_after)
        deadline = min(deadline, relative) if deadline is not None else relative
    if end.on:
        earliest = max(admitted_at, triggered) if triggered is not None else admitted_at
        if triggered is None and isinstance(trigger, EventTrigger) and trigger.window:
            earliest = max(earliest, at_time(trigger.window.from_))
        sources = {"hub"} if end.on in HomeEvent else {action.device for action in task.actions}
        for event in events:
            at = at_time(event.at)
            if deadline is not None and at > deadline:
                break
            if (
                event.type == end.on
                and event.source in sources
                and at >= earliest
                and (end.by is None or event.payload.by == end.by)
            ):
                return at + duration(end.after)
    return deadline


def user_changed(task: Task, runs: list[RunResult], events: list[Event], ended_at: datetime | None):
    actions = {(action.device, action.cmd) for action in task.actions}
    completed = [
        at_time(run.at) for run in runs
        if run.status == ExecutionStatus.COMPLETED and (run.device, run.cmd) in actions
    ]
    if not completed:
        return False
    first = min(completed)
    devices = {action.device for action in task.actions}
    return any(
        event.type.endswith(".changed")
        and event.payload.by == By.USER
        and event.source in devices
        and first < at_time(event.at)
        and (ended_at is None or at_time(event.at) <= ended_at)
        for event in events
    )


def restore_state(statuses: set[RestoreItemStatus]) -> EndState:
    if statuses & {RestoreItemStatus.FAILED, RestoreItemStatus.UNKNOWN}:
        return EndState.RESTORE_FAILED
    if RestoreItemStatus.WITHHELD_END_NOT_OBSERVED in statuses:
        return EndState.WITHHELD
    if RestoreItemStatus.SKIPPED_USER_CHANGED in statuses:
        return EndState.KEPT_USER_CHANGE
    return EndState.RESTORED


def line_end(
    task: Task, ended_at: datetime | None, now: datetime,
    latest: list[RunResult], restore: RestoreResult | None, cancelled: bool | None,
) -> tuple[bool, EndState | None]:
    if cancelled is not None:
        if not cancelled:
            return True, None
        if restore is None:
            return False, None
        return True, restore_state({item.status for item in restore.items})

    restored_at = at_time(restore.at) if restore else None
    if ended_at is None or (ended_at > now and (restored_at is None or ended_at > restored_at)):
        return False, None
    if not task.end.restore:
        return True, EndState.NONE
    if restored_at is not None and restored_at >= ended_at:
        return True, restore_state({item.status for item in restore.items})
    # A line with no dispatched action has no restore result to wait for.
    return all(result.status == ExecutionStatus.BLOCKED for result in latest), None
