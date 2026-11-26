"""Loopback access, request receipts and deterministic transport faults."""

import asyncio
from collections import Counter, deque
from datetime import datetime
from ipaddress import ip_address
from random import Random
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from spira_contracts.error import Error
from spira_contracts.health import Health
from starlette.requests import Request
from starlette.responses import JSONResponse

from .observation import SEOUL
from .replay import wire

Group = Literal["app", "hub", "clock", "health"]
SHELL_HEADER = "X-SPIRA-Demo-Client"
ERROR_CODES = {
    400: "invalid_image", 401: "unauthorized", 403: "forbidden", 404: "not_found",
    409: "stale_revision", 500: "internal", 503: "internal",
}
FAULT_SOURCE = "synthetic · contracts/rules.md:89"
ROUTES = {
    "order": ("app", "POST", "/v1/orders"),
    "edit": ("app", "PUT", "/v1/episodes/{id}/order"),
    "plans": ("hub", "GET", "/v1/hub/plans"),
    "events": ("hub", "POST", "/v1/hub/events"),
    "executions": ("hub", "POST", "/v1/hub/executions"),
    "clock-read": ("clock", "GET", "/v1/demo/clock"),
}
WRITES = {"POST", "PUT", "DELETE", "PATCH"}


class ControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Fault(ControlInput):
    group: Group
    kind: Literal["latency", "status", "apply_then_fail", "drop"]
    count: int | None = Field(default=1, ge=1, le=10_000)
    delay_ms: int | None = Field(default=None, ge=1, le=120_000)
    status: int | None = None
    route: Literal["order", "edit", "plans", "events", "executions", "clock-read"] | None = None

    @model_validator(mode="after")
    def check_options(self):
        if self.route and ROUTES[self.route][0] != self.group:
            raise ValueError("The route is outside the fault group")
        if (self.kind == "latency") != (self.delay_ms is not None):
            raise ValueError("Only latency requires delay_ms")
        if self.kind == "status":
            if self.status not in ERROR_CODES:
                raise ValueError("Select a supported HTTP status")
            if self.group == "health" and self.status != 503:
                raise ValueError("Health status faults use 503 degraded")
            if self.status in (400, 409) and (self.status, self.route) not in ((400, "order"), (409, "edit")):
                raise ValueError("This refusal needs its specific App route")
        elif self.status is not None:
            raise ValueError("Only status faults take a status")
        if self.kind == "apply_then_fail" and (
            self.group == "health" or (self.route and ROUTES[self.route][1] not in WRITES)
        ):
            raise ValueError("Apply then fail requires a write")
        return self

    def matches(self, method, path):
        if self.kind == "apply_then_fail" and method not in WRITES:
            return False
        if not self.route:
            return True
        _, verb, target = ROUTES[self.route]
        if method != verb:
            return False
        if self.route == "edit":
            head, _, tail = path.rpartition("/")
            return head.startswith("/v1/episodes/") and head.count("/") == 3 and tail == "order"
        return target == path

    def entry(self):
        source = FAULT_SOURCE
        if self.group == "health":
            source += " · contracts/schemas/health.json"
        return {**self.model_dump(), "source": source}

    def refusal(self, label):
        status = self.status if self.kind == "status" else 503
        if self.group == "health":
            body = Health(status="degraded")
        else:
            code = ERROR_CODES[status]
            body = Error(code=code, message=f"{label}. Synthetic {code} ({status}); {FAULT_SOURCE}")
        return JSONResponse(wire(body), status_code=status)


def route_group(path):
    if path == "/health":
        return "health"
    if path.startswith("/v1/demo/"):
        return "clock"
    if path.startswith("/v1/hub/"):
        return "hub"
    if path.startswith("/v1/"):
        return "app"
    return None


def is_loopback(host):
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def local_control(request):
    host = request.url.hostname
    origin = request.headers.get("origin")
    return (
        request.client is not None and is_loopback(request.client.host)
        and (host == "localhost" or (host and is_loopback(host)))
        and (origin is None or origin == f"{request.url.scheme}://{request.url.netloc}")
        and request.headers.get("sec-fetch-site") != "cross-site"
    )


class ConnectionDropped(ConnectionError):
    pass


class Traffic:
    def __init__(self):
        self.faults: dict[str, Fault] = {}
        self.log = deque(maxlen=300)
        self.serial = 0
        self.last = {}
        self.set_realistic(None)

    def set_realistic(self, seed):
        self.realistic_seed = seed
        self.realistic_reads = Counter()
        rng = Random(seed)
        self.realistic_failure = rng.randint(2, 5) if seed is not None else None

    def realistic_reply(self, method, path):
        if self.realistic_seed is None or route_group(path) != "app":
            return 0, None
        key = (method, path)
        self.realistic_reads[key] += 1
        count = self.realistic_reads[key]
        rng = Random(f"{self.realistic_seed}:{method}:{path}:{count}")
        delay = rng.randint(35, 420)
        if method == "GET" and path.endswith("/rationale") and count == self.realistic_failure:
            return delay, Fault(group="app", kind="status", status=503)
        return delay, None

    def take_fault(self, method, path):
        group = route_group(path)
        fault = self.faults.get(group)
        if fault is None or not fault.matches(method, path):
            return None
        if fault.count == 1:
            del self.faults[group]
        elif fault.count is not None:
            self.faults[group] = fault.model_copy(update={"count": fault.count - 1})
        return fault

    def record(self, request, at, started, status, fault):
        self.serial += 1
        path = request.url.path
        if path == "/_fixture/control" or path.startswith("/_fixture/control/"):
            client = "loopback-control" if local_control(request) else "anonymous"
        elif request.headers.get("X-API-Key"):
            client = "hub"
        elif request.headers.get("Authorization", "").lower().startswith("bearer "):
            client = "app"
        elif request.client and is_loopback(request.client.host):
            client = "loopback-control"
        else:
            client = "anonymous"
        shell = request.headers.get(SHELL_HEADER) == "shell"
        row = {
            "id": self.serial, "at": at.isoformat(), "client": client,
            "surface": "shell" if shell else None, "method": request.method, "path": path,
            "status": status, "latency_ms": round((monotonic() - started) * 1000, 2),
            "fault": fault.entry() if fault else None,
        }
        self.log.append(row)
        if request.method == "GET":
            if client == "hub" and path == "/v1/hub/plans":
                self.last["hub_pull"] = row
            if client == "app" and not shell and path.startswith("/v1/households/") and path.endswith("/cards"):
                self.last["app_card_poll"] = row
        if shell:
            self.last["shell_request"] = row


class RehearsalTraffic:
    def __init__(self, app, *, traffic, label, label_header):
        self.app = app
        self.traffic = traffic
        self.label = label
        self.label_header = label_header

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        at, started = datetime.now(SEOUL), monotonic()
        fault = self.traffic.take_fault(request.method, request.url.path)
        delay, realistic_fault = self.traffic.realistic_reply(request.method, request.url.path)
        fault = fault or realistic_fault
        status = None
        replace = False

        async def capture(message):
            nonlocal status, replace
            if message["type"] == "http.response.start":
                if delay:
                    await asyncio.sleep(delay / 1000)
                status = message["status"]
                replace = fault is not None and fault.kind == "apply_then_fail" and 200 <= status < 300
            if not replace:
                await send(message)

        try:
            if fault and fault.kind == "latency":
                await asyncio.sleep(fault.delay_ms / 1000)
            if fault and fault.kind == "drop":
                # ASGI has no disconnect message for HTTP responses. A truncated
                # response makes Uvicorn close the socket without a complete reply.
                await send({"type": "http.response.start", "status": 503, "headers": [
                    (b"content-length", b"1"),
                    (self.label_header.lower().encode(), self.label.encode()),
                ]})
                raise ConnectionDropped("Synthetic fixture connection drop")
            if fault and fault.kind == "status":
                reply = fault.refusal(self.label)
                reply.headers[self.label_header] = self.label
                await reply(scope, receive, capture)
            else:
                await self.app(scope, receive, capture)
            if replace:
                reply = fault.refusal(self.label)
                reply.headers[self.label_header] = self.label
                status = reply.status_code
                await reply(scope, receive, send)
        except ConnectionDropped:
            raise
        except Exception:
            status = status or 500
            raise
        finally:
            applied = fault if fault and (fault.kind != "apply_then_fail" or replace) else None
            self.traffic.record(request, at, started, status, applied)
