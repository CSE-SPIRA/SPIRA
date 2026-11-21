"""Read-only inputs for stage overlays and received C-3 evidence."""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import AwareDatetime, BaseModel, StrictBool, TypeAdapter
from spira_contracts.common import ExecutionStatus, Substrate, TaskSource, TriggerEvent
from spira_contracts.event import Event
from spira_contracts.event_batch import EventBatch
from spira_contracts.execution_result import ExecutionResult, RestoreResult, RunResult
from spira_contracts.plan import EventTrigger, Plan, TimeTrigger
from spira_contracts.plan_pull import PlanPull

from .profile import public_value
from .world import PEOPLE


class Source(Protocol):
    async def fetch(self): ...


class JsonSource:
    def __init__(self, location: str, headers: dict[str, str] | None = None):
        self.location = location
        self.headers = headers

    async def fetch(self):
        if self.location.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(self.location, headers=self.headers)
                response.raise_for_status()
                return response.json()
        return json.loads(Path(self.location).read_text(encoding="utf-8"))


class HubEvidence[Packet](BaseModel):
    delivered: StrictBool
    delivery_error: str | None
    packet: Packet


class HubTaskStory(BaseModel):
    plan_id: str
    task_id: str
    steps: list[dict]


class RunEvidence(BaseModel):
    plan_id: str
    task_id: str
    device: str
    at: AwareDatetime
    substrate: Substrate


received_events = TypeAdapter(list[Event])
received_batches = TypeAdapter(list[EventBatch])
execution_records = TypeAdapter(list[ExecutionResult])
plan_source = TypeAdapter(Plan | PlanPull)
hub_events = TypeAdapter(list[HubEvidence[EventBatch]])
hub_restores = TypeAdapter(list[HubEvidence[RestoreResult]])
hub_stories = TypeAdapter(list[HubTaskStory])


def hub_rows(payload, field: str):
    if not isinstance(payload, dict) or field not in payload:
        raise ValueError(f"Hub state is missing {field}")
    return payload[field]


def execution_evidence(payload, *, from_hub: bool):
    if from_hub:
        stories = hub_stories.validate_python(hub_rows(payload, "task_stories"))
        # Task stories expose local run outcomes. Their C-4 delivery is not in /state.
        runs = [
            RunEvidence.model_validate(
                {**step, "plan_id": story.plan_id, "task_id": story.task_id}
            )
            for story in stories
            for step in story.steps
            if step.get("kind") in ("command", "execution_block")
            and step.get("phase") == "run"
            and step.get("status") in ExecutionStatus
        ]
        reports = hub_restores.validate_python(hub_rows(payload, "restoration"))
        triggered = {
            (story.plan_id, story.task_id) for story in stories
            if any(step.get("kind") == "triggered" for step in story.steps)
        }
        return runs, [(row.packet, row.delivered) for row in reports], triggered

    if isinstance(payload, dict):
        payload = payload.get("executions")
    records = [row.root for row in execution_records.validate_python(payload)]
    runs = [
        RunEvidence.model_validate(record, from_attributes=True)
        for record in records
        if isinstance(record, RunResult)
    ]
    return runs, [(record, None) for record in records if isinstance(record, RestoreResult)], set()


async def stage_overlay(
    household_id: str,
    plans: Source | None,
    executions: Source | None,
    *,
    now: datetime,
    from_hub: bool = False,
) -> dict:
    errors = []
    plan_payload = None
    run_evidence, restore_evidence = [], []
    triggered = set()
    if plans:
        try:
            plan_payload = plan_source.validate_python(await plans.fetch())
        except (OSError, ValueError, httpx.HTTPError):
            errors.append("Plan source unavailable")
    if executions:
        try:
            run_evidence, restore_evidence, triggered = execution_evidence(
                await executions.fetch(), from_hub=from_hub
            )
        except (OSError, ValueError, httpx.HTTPError):
            errors.append("Execution source unavailable")

    stage_plans = [plan_payload] if isinstance(plan_payload, Plan) else []
    if isinstance(plan_payload, PlanPull) and plan_payload.household_id == household_id:
        stage_plans = plan_payload.plans

    runs = {}
    for record in run_evidence:
        key = (record.plan_id, record.task_id, record.device)
        if key not in runs or record.at > runs[key].at:
            runs[key] = record
    preparation = []
    notices = []
    guest_windows = []
    has_preparation = False
    for plan in stage_plans:
        if plan.household_id != household_id:
            continue
        cancelled = {task.task_id for task in plan.cancelled}
        for task in plan.tasks:
            if task.task_id in cancelled:
                continue
            wait = (
                task.trigger.time
                if isinstance(task.trigger, TimeTrigger)
                else task.trigger.event.value
            )
            item_notice = task.source == TaskSource.ITEM
            has_preparation |= not item_notice
            overlay = notices if item_notice else preparation
            window = None
            if isinstance(task.trigger, EventTrigger) and task.trigger.event == TriggerEvent.GUEST_ARRIVED:
                if task.trigger.window:
                    window = task.trigger.window.model_dump(by_alias=True)
                    if window not in guest_windows:
                        guest_windows.append(window)
            missed = (
                window is not None and now > datetime.fromisoformat(window["to"])
                and not errors
                and (plan.plan_id, task.task_id) not in triggered
                and not any((plan.plan_id, task.task_id, action.device) in runs for action in task.actions)
            )
            for action in task.actions:
                if (
                    plan.plan_id,
                    task.task_id,
                    action.device,
                ) not in runs and public_value(action.value):
                    overlay.append(
                        {
                            "plan_id": plan.plan_id,
                            "task_id": task.task_id,
                            "device": action.device,
                            "command": action.cmd,
                            # Item notice text stays out of the stage (E5-R6).
                            "target_value": None if item_notice else action.value,
                            "wait": wait,
                            "protective": task.protective is True,
                            **({"window": window, "missed": missed} if window else {}),
                        }
                    )

    restores = []
    for record, delivered in restore_evidence:
        for item in record.items:
            run = runs.get((record.plan_id, record.task_id, item.device))
            substrate = run.substrate.value if run else None
            qualification = {"virtual": "virtual_only", "physical": "unqualified"}.get(
                substrate
            )
            row = {
                "plan_id": record.plan_id,
                "task_id": record.task_id,
                "at": record.at,
                "device": item.device,
                "status": item.status.value,
                "substrate": substrate,
                "qualification": qualification,
            }
            if delivered is not None:
                row["delivery"] = "delivered" if delivered else "not_delivered"
            restores.append(row)
    return {
        "preparation": preparation,
        "notices": notices,
        "guest_windows": sorted(guest_windows, key=lambda window: datetime.fromisoformat(window["from"])),
        "has_preparation": has_preparation,
        "restores": restores,
        "errors": errors,
    }


def _verdict(actor: str, by: str) -> str | None:
    if by == "unknown" and actor in PEOPLE:
        return "person-reported-unknown"
    if by == "user":
        if actor in {"child", "guest"}:
            return "person-not-decision-maker"
        return "match" if actor == "resident" else "non-person-reported-user"
    if (actor, by) in {
        ("spira", "spira"),
        ("external_automation", "unknown"),
        ("device_self", "unknown"),
    }:
        return "match"
    return None


async def judge(
    household_id: str, truth: list[dict], source: Source, *, from_hub: bool = False
) -> dict:
    payload = await source.fetch()
    pending = []
    if from_hub:
        rows = hub_events.validate_python(hub_rows(payload, "events"))
        received = [event for row in rows if row.delivered for event in row.packet.root]
        pending = [
            {
                "event_id": event.event_id,
                "device": event.source,
                "event_type": event.type,
                "at": event.at,
                "delivery_error": row.delivery_error,
            }
            for row in rows if not row.delivered
            for event in row.packet.root
            if event.household_id == household_id and event.source != "hub"
        ]
    elif isinstance(payload, dict):
        batches = received_batches.validate_python(payload.get("events"))
        received = [event for batch in batches for event in batch.root]
    else:
        received = received_events.validate_python(payload)
    candidates = defaultdict(list)
    for fact in truth:
        if fact["logical_id"] is not None:
            key = (
                fact["logical_id"],
                fact["event_type"],
                datetime.fromisoformat(fact["occurred_at"]),
            )
            candidates[key].append(fact)

    results = []
    unresolved = []
    seen = set()
    for event in received:
        if (
            event.household_id != household_id
            or event.source == "hub"
            or event.event_id in seen
        ):
            continue
        seen.add(event.event_id)
        key = (event.source, event.type, datetime.fromisoformat(event.at))
        matches = candidates.get(key, [])
        by = event.payload.by
        comparison = {"event_id": event.event_id, "by": by.value if by else None}
        if len(matches) != 1:
            unresolved.append(
                {
                    **comparison,
                    "reason": (
                        "ambiguous_occurrence" if matches else "no_matching_truth"
                    ),
                }
            )
            continue
        fact = matches[0]
        verdict = _verdict(fact["actor"], by.value) if by else None
        if verdict is None:
            unresolved.append(
                {**comparison, "truth": fact, "reason": "undefined_attribution"}
            )
        else:
            results.append({**comparison, "truth": fact, "verdict": verdict})
    return {
        "source": "hub_state" if from_hub else "fixture_receipts",
        "results": results,
        "unresolved": unresolved,
        "not_delivered": [row for row in pending if row["event_id"] not in seen],
    }
