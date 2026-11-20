"""Versioned admission and trigger/lifecycle frontiers."""

import json

from spira_contracts.ack import Ack, RejectedTask
from spira_contracts.common import HomeEvent

from .contracts import duration, offset_time, packet, value_reason, wire
from .store import encode

HOME_EVENTS = {event.value for event in HomeEvent}


def admit(store, plan, malformed, installation, now):
    plan_id, version = plan.plan_id, plan.plan_version
    previous_version = store.floor(plan_id)
    if version <= previous_version:
        return
    rejected = {task_id: "schema" for task_id in malformed}
    current = {}
    for task in plan.tasks:
        reason = task_reason(task, installation.delegates)
        if reason:
            rejected[task.task_id] = reason
        else:
            current[task.task_id] = wire(task)
    ack = Ack(
        plan_version=version, status="admitted",
        rejected_tasks=[RejectedTask(task_id=task_id, reason=reason)
                        for task_id, reason in sorted(rejected.items())],
    )
    cancelled = {entry.task_id: entry.restore for entry in plan.cancelled}
    previous = {task["id"]: task for task in store.tasks(plan_id)}
    triggers = {task_id: body["trigger"] for task_id, body in current.items()}
    previous_triggers = {task_id: task["body"]["trigger"] for task_id, task in previous.items()
                         if task["active"]}
    store.save_plan_version(plan_id, version, {
        "received_at": now.isoformat(), "triggers": triggers, "previous_version": previous_version or None,
        "changes": {
            "added": sorted(triggers.keys() - previous_triggers.keys()),
            "removed": sorted(previous_triggers.keys() - triggers.keys()),
            "cancelled": [{"task_id": task_id, "restore": restore} for task_id, restore in cancelled.items()
                          if previous.get(task_id, {}).get("cancel") != restore],
            "triggers_changed": [
                {"task_id": task_id, "from": previous_triggers[task_id], "to": triggers[task_id]}
                for task_id in sorted(previous_triggers.keys() & triggers.keys())
                if previous_triggers[task_id] != triggers[task_id]
            ],
        },
    })
    frontier = store.frontier()
    for task_id in dict.fromkeys([*current, *previous, *cancelled]):
        task = previous.get(task_id, {
            "plan": plan_id, "id": task_id, "body": None, "cancel": None,
            "triggered_at": None, "admitted_at": now.isoformat(), "frontier": frontier,
            "closed": None, "restore_reported": [], "restore_items": {},
        })
        if task_id in cancelled:
            task["cancel"] = cancelled[task_id]
        body = current.get(task_id)
        if body and task["cancel"] is None:
            if not task["body"] or task["body"]["trigger"] != body["trigger"]:
                # Started work keeps its original trigger and base time.
                if not any(attempt["before"] for attempt in store.attempts(task=task)):
                    task.update(admitted_at=now.isoformat(), frontier=frontier, triggered_at=None)
            task["body"] = body
            task["substrates"] = {
                action["device"]: installation.delegates[action["device"]].substrate.value
                for action in body["actions"]
            }
        task["active"] = body is not None and task["cancel"] is None
        if task["cancel"] is False:
            for attempt in store.attempts(task=task):
                if attempt["claims"]:
                    attempt["claims"] = {}
                    store.save_attempt(attempt)
        task["version"] = version
        store.save_task(task)
    store.advance(plan_id, version)
    store.queue(
        f"{plan_id}/{version}", "ack", f"/v1/hub/plans/{plan_id}/ack",
        now.timestamp(), packet(ack, "ack.json"),
    )


def task_reason(task, devices):
    for action in task.actions:
        device = devices.get(action.device)
        if device is None:
            return "unknown_device"
        command = delegated(device, action.cmd)
        if command is None:
            return "unsupported_cmd"
        if reason := value_reason(action, command):
            return reason
    return None


def delegated(device, command):
    if device is None or command in device.never:
        return None
    return next((entry for entry in device.commands if entry.cmd == command), None)


def action_keys(task):
    counts = {}
    for action in task["body"]["actions"]:
        body = encode(action)
        count = counts.get(body, 0)
        counts[body] = count + 1
        yield encode([action, count]), action


def trigger_time(store, task, now):
    match = trigger_match(store, task, now)
    return offset_time(match["at"]) if match else None


def trigger_match(store, task, now):
    if task["triggered_at"]:
        return {"at": task["triggered_at"]}
    trigger = task["body"]["trigger"]
    if "time" in trigger:
        return {"at": trigger["time"], "how": "time"} if offset_time(trigger["time"]) <= now else None
    if trigger.get("released") is False:
        return None
    if trigger["event"] == "package.brought_in":
        # The Server alone links a brought-in package to an order.
        if trigger.get("released") is not True or not trigger.get("at"):
            return None
        return ({"at": trigger["at"], "how": "server_release", "event_type": trigger["event"]}
                if offset_time(trigger["at"]) <= now else None)
    window = trigger.get("window")
    earliest = offset_time(task["admitted_at"])
    latest = now
    if window:
        earliest = max(earliest, offset_time(window["from"]))
        latest = min(latest, offset_time(window["to"]))
    for row in store.facts(after=task["frontier"], earliest=earliest.timestamp()):
        event = json.loads(row["body"])
        at = offset_time(event["at"])
        if at > latest:
            break
        if (event["source"] == "hub" and event["type"] == trigger["event"]
                and offset_time(event.get("evidence_from", event["at"])) >= earliest):
            return {"at": event["at"], "how": "event", "event_type": event["type"],
                    "event_id": event["event_id"], "source": event["source"]}
    return None


def end_status(store, task, now, *, started_at=None):
    match = end_match(store, task, now, started_at=started_at)
    return match["disposition"] if match else None


def notice_end(task):
    body = task["body"]
    return (body["source"] == "item" and body["way"] == "notice"
            and any(action["device"] == "fridge_01" and action["cmd"] == "show_notice"
                    for action in body["actions"]))


def end_match(store, task, now, *, started_at=None):
    """Return the lifecycle disposition and the condition that selected it."""
    end = task["body"]["end"]
    if task["cancel"] is not None:
        return {"at": now.isoformat(), "how": "cancelled", "restore": task["cancel"],
                "disposition": "restore" if task["cancel"] else "relinquished"}
    # A withheld task has ended, but its claims can still serve explicit cancellation.
    if task["closed"] == "withheld_end_not_observed":
        return None

    clear_notice = notice_end(task)
    absolute = end.get("or_time", end.get("time"))
    deadline = offset_time(absolute) if absolute else None
    rule = "or_time" if "or_time" in end else "time"
    if task["triggered_at"] and "or_after" in end:
        relative = offset_time(task["triggered_at"]) + duration(end["or_after"])
        if deadline is None or relative < deadline:
            deadline, rule = relative, "or_after"
    if started_at and end.get("on"):
        # A door opening can reach the Hub before the Server's release version.
        notice_open = clear_notice and end["on"] == "fridge.door_opened"
        earliest = started_at if notice_open else max(offset_time(task["admitted_at"]), started_at)
        frontier = 0 if notice_open else task["frontier"]
        devices = {action["device"] for action in task["body"]["actions"]}
        for row in store.facts(after=frontier, earliest=earliest.timestamp()):
            event = json.loads(row["body"])
            if event["type"] != end["on"]:
                continue
            if offset_time(event.get("evidence_from", event["at"])) < earliest:
                continue
            if end["on"] not in HOME_EVENTS and event["source"] not in devices:
                continue
            if end.get("by") and event["payload"].get("by") != end["by"]:
                continue
            at = offset_time(event["at"])
            if notice_open and at <= started_at:
                continue
            if at > now or (deadline is not None and at > deadline):
                break
            if "after" in end:
                at += duration(end["after"])
            if at > now:
                return None
            return {"at": at.isoformat(), "how": "event", "event_type": event["type"],
                    "event_id": event["event_id"], "event_at": event["at"], "source": event["source"],
                    "disposition": ("clear_notice" if clear_notice else
                                    "restore" if end["restore"] else "relinquished")}
    if deadline is not None and deadline <= now:
        disposition = "relinquished"
        if clear_notice:
            disposition = "clear_notice"
        elif end["restore"]:
            disposition = "withheld_end_not_observed" if task["body"].get("protective") else "restore"
        return {"at": deadline.isoformat(), "how": "time" if rule == "time" else "fallback",
                "rule": rule, "disposition": disposition}
    return None
