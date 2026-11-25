"""Server HTTP and generated C-1–C-4 conversion."""

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx2 as httpx
from spira_contracts.devices import Command, Devices, Param1
from spira_contracts.devices_response import DevicesResponse
from spira_contracts.event_response import EventResponse
from spira_contracts.execution_response import ExecutionResponse
from spira_contracts.plan import Action, Task
from spira_contracts.plan_pull import PlanPull
from spira_contracts.validate import ContractError, validate

from .store import encode


def wall_time():
    return datetime.now(timezone.utc)


ISO_INSTANT = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d+))?(?:Z|[+-]\d{2}:\d{2})"
)


def offset_time(value):
    if not isinstance(value, str) or not ISO_INSTANT.fullmatch(value):
        raise ValueError("Expected an ISO 8601 timestamp with an offset")
    return datetime.fromisoformat(value)


def timestamp_precision(value):
    """Precision in microseconds of a validated wire timestamp."""
    fraction = ISO_INSTANT.fullmatch(value).group(1) or ""
    return timedelta(microseconds=10 ** (6 - min(len(fraction), 6)))


def no_earlier_than(value, instant):
    # A seconds-only sender records the containing second, while the Hub records microseconds.
    return instant - offset_time(value) < timestamp_precision(value)


def duration(value):
    scale = 60 if value[-1] == "m" else 3600
    return timedelta(seconds=int(value[:-1]) * scale)


def identity(prefix):
    return f"{prefix}_{uuid4().hex}"


def wire(model):
    return model.model_dump(mode="json", by_alias=True, exclude_unset=True)


def packet(model, schema):
    body = wire(model)
    validate(body, schema)
    return encode(body).encode()


def read_model(model, body, schema):
    validate(body, schema)
    return model.model_validate(body)


class Server:
    def __init__(self, http: httpx.AsyncClient, household: str, *, clock=wall_time):
        self.http = http
        self.household = household
        self.clock = clock
        self.fixture = None

    async def pull(self):
        response = await self.http.get("/v1/hub/plans", params={"household": self.household})
        response.raise_for_status()
        self.fixture = response.headers.get("X-SPIRA-Fixture")
        return parse_pull(response.json(), self.household, clock=self.clock)

    async def register(self, devices: Devices):
        response = await self.http.put(
            f"/v1/hub/households/{self.household}/devices",
            content=packet(devices, "devices.json"),
        )
        response.raise_for_status()
        return read_model(DevicesResponse, response.json(), "devices_response.json").revision

    async def send(self, item):
        response = await self.http.post(item["path"], content=item["packet"])
        response.raise_for_status()
        match item["kind"]:
            case "ack":
                if response.status_code != 204:
                    raise ValueError("Unexpected acknowledgement response")
            case "event":
                return read_model(EventResponse, response.json(), "event_response.json")
            case "execution":
                read_model(ExecutionResponse, response.json(), "execution_response.json")


def parse_pull(body, household, *, clock=wall_time):
    """Validate envelopes separately so malformed addressable lines keep valid siblings."""
    if not isinstance(body, dict) or not isinstance(body.get("plans"), list):
        raise ContractError("Unreadable plan snapshot")
    cleaned = []
    invalid = {}
    for plan in body["plans"]:
        if not isinstance(plan, dict) or not isinstance(plan.get("tasks"), list):
            raise ContractError("Unreadable plan envelope")
        offset_time(plan.get("sent_at", ""))
        ids = Counter(
            task.get("task_id") for task in plan["tasks"]
            if isinstance(task, dict) and isinstance(task.get("task_id"), str)
        )
        cancelled = plan.get("cancelled")
        if not isinstance(cancelled, list):
            raise ContractError("Unreadable cancellation list")
        cancelled_ids = {
            item["task_id"] for item in cancelled
            if isinstance(item, dict) and isinstance(item.get("task_id"), str)
        }
        valid = []
        rejected = set()
        for task in plan["tasks"]:
            if not isinstance(task, dict) or not isinstance(task.get("task_id"), str):
                continue
            task_id = task["task_id"]
            if not re.fullmatch(r"t_[a-z][a-z0-9_]*#[0-9]+", task_id):
                continue
            try:
                read_model(Task, task, "plan.json#/$defs/Task")
                check_task_times(task, clock)
            except (ValueError, OverflowError):
                rejected.add(task_id)
                continue
            if ids[task_id] > 1 or task_id in cancelled_ids:
                rejected.add(task_id)
            else:
                valid.append(task)
        envelope = {**plan, "tasks": valid}
        validate(envelope, "plan.json")
        if plan["household_id"] != household or plan["plan_id"] in invalid:
            raise ContractError("Unexpected household or duplicate plan in snapshot")
        invalid[plan["plan_id"]] = sorted(rejected)
        cleaned.append(envelope)
    pull = read_model(PlanPull, {**body, "plans": cleaned}, "plan_pull.json")
    if pull.household_id != household:
        raise ContractError("Unexpected household")
    return pull, invalid


def check_task_times(task, clock=wall_time):
    for name in ("time", "at"):
        if name in task["trigger"]:
            offset_time(task["trigger"][name])
    for value in task["trigger"].get("window", {}).values():
        offset_time(value)
    for name in ("time", "or_time"):
        if name in task["end"]:
            offset_time(task["end"][name])
    for name in ("after", "or_after"):
        if name in task["end"]:
            # A syntactically valid duration must still be representable.
            clock() + duration(task["end"][name])


def value_reason(action: Action, command: Command):
    schema, value = command.value_schema, action.value
    if schema is None:
        return None if value is None else "schema"
    if schema == "text":
        return None if command.cmd == "show_notice" and isinstance(value, str) else "schema"
    if not isinstance(value, dict) or value.keys() != schema.keys():
        return "schema"
    for name, param in schema.items():
        candidate = value[name]
        definition = param.root
        if isinstance(definition, Param1):
            if not isinstance(candidate, (int, float)):
                return "schema"
            low, high = definition.range
            if not low <= candidate <= high:
                return "value_out_of_range"
        elif not isinstance(candidate, str):
            return "schema"
        elif candidate not in definition.enum:
            return "value_out_of_range"
    return None


def packet_body(item):
    return json.loads(item["packet"])
