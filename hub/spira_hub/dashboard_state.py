"""Project the Hub's durable records for the local dashboard."""

import json
from collections import defaultdict
from datetime import datetime, timezone

from .contracts import offset_time, packet_body
from .plans import action_keys, trigger_match

RUN_PROBLEMS = {"failed", "unknown", "unverifiable"}


def state_view(runtime):
    store = runtime.store
    now = runtime.clock()
    snapshot = store.get("snapshot", {})
    current_plans = set(snapshot.get("plans", []))
    attempts = store.attempts()
    attempts_by_task = defaultdict(list)
    for attempt in attempts:
        attempts_by_task[attempt["plan"], attempt["task"]].append(attempt)
    restores = []
    restores_by_task = defaultdict(list)
    for row in reversed(store.evidence("execution", limit=-1)):
        result = packet_body(row)
        if result["kind"] == "restore":
            restores.append(evidence(row, result))
            restores_by_task[result["plan_id"], result["task_id"]].append(result)

    history, admissions = plan_history(store)
    summaries = {}
    for version in history:
        plan_id = version["plan_id"]
        summaries[plan_id] = {
            "plan_id": plan_id, "plan_version": version["plan_version"],
            "current": plan_id in current_plans, "device_actions": 0, "notices": 0,
            "waiting": 0, "window_passed": 0, "triggered": 0, "completed": 0,
            "failed_unknown_unverifiable": 0, "restored": 0, "withheld": 0,
        }

    waiting, stories = [], []
    changes = person_changes(store, attempts)
    for task in store.tasks():
        plan_id, task_id = key = task["plan"], task["id"]
        task_attempts = attempts_by_task[key]
        results = restores_by_task[key]
        if task["active"]:
            actions = dict(action_keys(task))
            tried = {attempt["action_key"]: attempt["status"] for attempt in task_attempts
                     if attempt["kind"] == "run" and attempt["action_key"] in actions}
            work = None
            if plan_id in current_plans:
                remaining = [action for action_key, action in actions.items() if action_key not in tried]
                work = waiting_work(store, task, remaining, now)
                if work:
                    waiting.append(work)
            summarize(summaries[plan_id], task, actions, tried, work, results)
        if task["body"] or admissions[key]:
            stories.append({
                "plan_id": plan_id, "task_id": task_id,
                "steps": task_story(task, admissions[key], task_attempts, changes, results),
            })

    return {
        "waiting": waiting, "commands": [command(row) for row in reversed(attempts[-100:])],
        "events": [evidence(row) for row in store.evidence("event")], "restoration": restores[-100:][::-1],
        "plan_history": history, "plan_summaries": list(summaries.values()), "task_stories": stories,
        "devices": device_bindings(runtime), "paused": snapshot.get("paused"),
        "server_peer": runtime.server.fixture, "server_error": runtime.last_pull_error,
        "registry_error": runtime.config_error, "observation_gap_at": runtime.observations.gap_at,
        "device_online": runtime.device.online,
    }


def waiting_work(store, task, remaining, now):
    trigger = task["body"]["trigger"]
    window = trigger.get("window")
    expired = (not task["triggered_at"] and window and now > offset_time(window["to"])
               and trigger_match(store, task, now) is None)
    if not expired and (task["closed"] or not remaining):
        return None
    row = {
        "plan_id": task["plan"], "plan_version": task["version"], "task_id": task["id"],
        "actions": remaining, "trigger": trigger, "triggered_at": task["triggered_at"],
        "status": "triggered" if task["triggered_at"] else "waiting",
    }
    if expired:
        row.update(status="window_passed", window_passed_at=window["to"])
    return row


def summarize(summary, task, actions, tried, work, results):
    summary["notices" if task["body"]["way"] == "notice" else "device_actions"] += 1
    if work and work["status"] in ("waiting", "window_passed"):
        summary[work["status"]] += 1
    summary["triggered"] += task["triggered_at"] is not None
    statuses = set(tried.values())
    summary["completed"] += len(tried) == len(actions) and statuses == {"completed"}
    summary["failed_unknown_unverifiable"] += bool(statuses & RUN_PROBLEMS)
    if results:
        items = {item["status"] for item in results[-1]["items"]}
        summary["restored"] += "restored" in items
        summary["withheld"] += "withheld_end_not_observed" in items


def plan_history(store):
    versions = store.plan_versions()
    history = []
    admissions = defaultdict(list)
    for row in reversed(store.evidence("ack", limit=-1)):
        plan_id, _ = row["id"].rsplit("/", 1)
        ack = evidence(row)
        version = ack["packet"]["plan_version"]
        saved = versions.get((plan_id, version))
        received_at = (saved["received_at"] if saved else
                       datetime.fromtimestamp(row["at"], timezone.utc).isoformat())
        history.append({
            "plan_id": plan_id, "plan_version": version, "received_at": received_at, "ack": ack,
            "previous_version": saved["previous_version"] if saved else None,
            "changes": saved["changes"] if saved else None,
        })
        if not saved:
            continue
        step = {"at": received_at, "plan_version": version}
        changes = saved["changes"]
        changed_triggers = {item["task_id"] for item in changes["triggers_changed"]}
        waiting = changed_triggers | set(changes["added"])
        for task_id, trigger in saved["triggers"].items():
            steps = admissions[plan_id, task_id]
            steps.append({"kind": "admitted", **step})
            if task_id in waiting or not any(item["kind"] == "waiting" for item in steps):
                steps.append({"kind": "waiting", "trigger": trigger, **step})
        for task_id in changes["removed"]:
            admissions[plan_id, task_id].append({"kind": "removed", **step})
        for item in changes["cancelled"]:
            admissions[plan_id, item["task_id"]].append({
                "kind": "cancelled", "restore": item["restore"], **step,
            })
    return history, admissions


def person_changes(store, attempts):
    sent = [offset_time(row["sent_at"]).timestamp() for row in attempts if row["before"] is not None]
    changes = defaultdict(list)
    if sent:
        for row in store.facts(earliest=min(sent)):
            event = json.loads(row["body"])
            if event["payload"].get("by") == "user":
                changes[event["source"], row["target"]].append(event)
    return changes


def task_story(task, admissions, attempts, changes, results):
    steps = list(admissions)
    if task["body"] and not any(step["kind"] == "waiting" for step in steps):
        steps.append({"kind": "waiting", "at": task["admitted_at"], "trigger": task["body"]["trigger"]})
    triggers = task.get("trigger_evidence", [])
    steps.extend({"kind": "triggered", **trigger} for trigger in triggers)
    if task["triggered_at"] and not triggers:
        steps.append({"kind": "triggered", "at": task["triggered_at"], "how": "unknown"})

    started = {}
    restore_commands = []
    for attempt in attempts:
        entry = command(attempt)
        entry["phase"] = entry.pop("kind")
        entry["plan_version"] = attempt["version"]
        entry["cmd"] = attempt["action"]["cmd"]
        entry["kind"] = "command" if attempt["before"] is not None else "execution_block"
        if entry["phase"] == "restore":
            restore_commands.append(entry)
        else:
            steps.append(entry)
            if attempt["before"] is not None:
                started.setdefault((entry["device"], entry["target"], entry["binding"]), offset_time(entry["at"]))

    closed_at = task.get("closed_at")
    if not closed_at and task["closed"] == "final" and results:
        closed_at = results[-1]["at"]
    if closed_at or task["closed"] != "final":
        closure = offset_time(closed_at) if closed_at else None
        for (device, target, epoch), onset in started.items():
            for event in changes[device, target]:
                at = offset_time(event["at"])
                if at < onset or (closure and at > closure):
                    continue
                if event.get("epoch", epoch) != epoch:
                    continue
                steps.append({
                    "kind": "person_change", "at": event["at"], "device": device,
                    "by": event["payload"]["by"], "event_type": event["type"],
                    "event_id": event["event_id"], "payload": event["payload"],
                })

    steps.extend({"kind": "end", **end["match"], "recorded_at": end["recorded_at"],
                  "plan_version": end["plan_version"]} for end in task.get("end_evidence", []))
    if task["closed"] and not task.get("end_evidence"):
        steps.append({"kind": "end", "how": "unknown", "at": closed_at})
    steps.extend(restore_commands)
    steps.extend({"kind": "restore_result", "at": result["at"], "plan_version": result["plan_version"],
                  "result_id": result["result_id"], "items": result["items"]} for result in results)
    return sorted(steps, key=story_time)


def story_time(step):
    at = step.get("recorded_at", step["at"])
    return offset_time(at) if at else datetime.max.replace(tzinfo=timezone.utc)


def command(row):
    return {
        "plan": row["plan"], "task": row["task"], "device": row["action"]["device"],
        "substrate": row["substrate"], "target": row["target"], "binding": row["epoch"],
        "operation_id": row["op"], "kind": row["kind"], "at": row["sent_at"],
        "desired": row["desired"], "acknowledgement": row["ack"],
        "read_back": row["read_back"], "status": row["status"], "reason": row.get("reason"),
    }


def evidence(row, body=None):
    return {"delivered": bool(row["delivered"]), "delivery_error": row["error"],
            "packet": packet_body(row) if body is None else body}


def device_bindings(runtime):
    devices = []
    for device in runtime.installation.devices.devices:
        target = runtime.installation.bindings[device.id].target
        capability = runtime.capabilities.get(target)
        devices.append({
            "device": device.id, "target": target, "substrate": device.substrate.value,
            "observed_substrate": capability.substrate if capability else None,
            "assumption": capability.assumption if capability else None,
        })
    return devices
