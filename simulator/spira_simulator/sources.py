"""Read-only inputs for stage overlays and received C-3 evidence."""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import TypeAdapter
from spira_contracts.event import Event
from spira_contracts.execution_result import ExecutionResult, RestoreResult
from spira_contracts.plan import Plan, TimeTrigger
from spira_contracts.plan_pull import PlanPull

from .profile import public_value
from .world import PEOPLE


class Source(Protocol):
    async def fetch(self): ...


class JsonSource:
    def __init__(self, location: str, token: str | None = None):
        self.location = location
        self.token = token

    async def fetch(self):
        if self.location.startswith(("http://", "https://")):
            headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(self.location, headers=headers)
                response.raise_for_status()
                return response.json()
        return json.loads(Path(self.location).read_text(encoding="utf-8"))


received_events = TypeAdapter(list[Event])
execution_records = TypeAdapter(list[ExecutionResult])
plan_source = TypeAdapter(Plan | PlanPull)


async def stage_overlay(
    household_id: str,
    plans: Source | None,
    executions: Source | None,
) -> dict:
    errors = []
    plan_payload = None
    records = []
    if plans:
        try:
            plan_payload = plan_source.validate_python(await plans.fetch())
        except (OSError, ValueError, httpx.HTTPError):
            errors.append("Plan source unavailable")
    if executions:
        try:
            records = [
                record.root
                for record in execution_records.validate_python(
                    await executions.fetch()
                )
            ]
        except (OSError, ValueError, httpx.HTTPError):
            errors.append("Execution source unavailable")

    stage_plans = [plan_payload] if isinstance(plan_payload, Plan) else []
    if isinstance(plan_payload, PlanPull) and plan_payload.household_id == household_id:
        stage_plans = plan_payload.plans

    runs = {}
    for record in records:
        if record.kind == "run":
            key = (record.plan_id, record.task_id, record.device)
            if key not in runs or datetime.fromisoformat(
                record.at
            ) > datetime.fromisoformat(runs[key].at):
                runs[key] = record
    preparation = []
    item_notices = []
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
            overlay = item_notices if task.source.value == "item" else preparation
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
                            "target_value": action.value,
                            "wait": wait,
                        }
                    )

    restores = []
    for record in records:
        if not isinstance(record, RestoreResult):
            continue
        for item in record.items:
            run = runs.get((record.plan_id, record.task_id, item.device))
            substrate = run.substrate.value if run else None
            qualification = {"virtual": "virtual_only", "physical": "unqualified"}.get(
                substrate
            )
            restores.append(
                {
                    "plan_id": record.plan_id,
                    "task_id": record.task_id,
                    "at": record.at,
                    "device": item.device,
                    "status": item.status.value,
                    "substrate": substrate,
                    "qualification": qualification,
                }
            )
    return {
        "preparation": preparation,
        "item_notices": item_notices,
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


async def judge(household_id: str, truth: list[dict], source: Source) -> dict:
    received = received_events.validate_python(await source.fetch())
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
    return {"results": results, "unresolved": unresolved}
