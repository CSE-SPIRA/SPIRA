"""Device facts, Hub attribution and property witnesses."""

import re

from spira_contracts.event import Event
from spira_contracts.event_batch import EventBatch

from .contracts import identity, offset_time, packet, wire
from .device import observable, report, watchable
from .store import encode


class Observations:
    def __init__(self, store, household, clock):
        self.store = store
        self.household = household
        self.clock = clock
        self.latest = {}
        self.baselines = {}
        self.job_starts = {}
        self.completed_jobs = {}
        self.sequences = {}
        self.gap_at = clock().isoformat()

    def gap(self):
        self.latest.clear()
        self.baselines.clear()
        self.job_starts.clear()
        self.completed_jobs.clear()
        self.sequences.clear()
        self.gap_at = self.clock().isoformat()

    def ingest(self, raw, installation, capabilities, bindings):
        if not watchable(raw):
            return
        if raw.get("kind") == "state_report":
            observation = report(raw)
            if observation:
                self.record(observation, installation, capabilities, bindings, pushed=True)
        elif raw.get("kind") == "event_signal" and isinstance(raw["event_type"], str):
            try:
                at = offset_time(raw["occurred_at"])
            except (KeyError, ValueError, TypeError):
                return
            payload = observable(raw.get("payload", {}))
            if not isinstance(payload, dict):
                return
            with self.store.db:
                if self.store.signal_is_new(raw["signal_id"]):
                    self.raw_event(raw, at, payload, installation)

    def record(self, observation, installation, capabilities, bindings, *, pushed=False):
        target = observation["target"]
        device = next((item for item in installation.devices.devices
                       if installation.bindings[item.id].target == target), None)
        if device is None or device.substrate.value != observation["substrate"]:
            return
        previous = self.latest.get(target)
        if previous and observation["world_revision"] < previous["world_revision"]:
            return
        if previous and observation["world_revision"] > previous["world_revision"]:
            self.baselines[target] = previous
        capability = capabilities.get(target)
        if capability is not None and (device.type != capability.device_type
                                       or observation["substrate"] != capability.substrate):
            return
        operation = self.store.operation(observation["operation_id"])
        epoch = bindings[device.id]["epoch"]
        if operation and (operation["target"] != target or operation["epoch"] != epoch
                          or operation["before"] is None):
            operation = None
        by = "unknown"
        if observation["local_operation"] and capability and capability.local_operation:
            by = "user"
        elif operation:
            by = "spira"

        with self.store.db:
            if pushed and not self.store.signal_is_new(observation["signal_id"]):
                return
            for attempt in self.store.attempts(target=target):
                if attempt["epoch"] != epoch:
                    continue
                self.reconcile(attempt, observation, operation)
            if operation and pushed and observation["available"]:
                operation = self.store.operation(operation["op"])
                update = operation.get("effect")
                if update is None or update["world_revision"] <= observation["world_revision"]:
                    operation["effect"] = observation
                    self.store.save_attempt(operation)
            if observation["event_type"] and observation["available"]:
                # The same explicit transition can arrive in both a push and a fresh read.
                fact_key = encode(["transition", epoch, observation["world_revision"],
                                   observation["event_type"], observation["occurred_at"]])
                if self.store.signal_is_new(fact_key):
                    baseline = previous
                    if previous and previous["world_revision"] == observation["world_revision"]:
                        baseline = self.baselines.get(target)
                    self.emit_device(device, observation, baseline, operation, by, epoch)
                    self.home_event(target, observation["event_type"], observation["occurred_at"],
                                    {}, installation)
        self.latest[target] = observation
        if by == "user" and observation["event_type"] == f"{device.type}.started":
            self.job_starts[target] = observation
        if observation["event_type"] == f"{device.type}.completed" and observation["operation_id"] is None:
            self.completed_jobs[target] = observation
        if observation["values"].get("in_use") is False:
            self.job_starts.pop(target, None)

    def reconcile(self, attempt, observation, operation):
        if not observation["available"] or not attempt.get("claims"):
            return
        if operation and operation["op"] == attempt["op"]:
            return
        released = False
        for prop, claim in attempt["claims"].items():
            if (claim["owned"] and prop in observation["revisions"]
                    and (observation["revisions"][prop] != claim["witness"]
                         or prop in observation["values"]
                         and observation["values"][prop] != claim["desired"])):
                claim["owned"] = False
                released = True
        if released:
            self.store.save_attempt(attempt)

    def emit_device(self, device, observation, previous, operation, by, epoch):
        kind = observation["event_type"]
        if not kind or not re.fullmatch(rf"{re.escape(device.type)}\.[a-z][a-z0-9_]*", kind):
            return
        if not kind.endswith(".changed"):
            self.emit(kind, device.id, observation["target"], observation["occurred_at"], {"by": by},
                      epoch=epoch)
            return
        before = previous
        if operation and (not before or before["world_revision"] >= observation["world_revision"]):
            before = operation["before"]
        values = observation["values"]
        changes = changed_properties(before, observation, operation)
        for prop in changes:
            self.emit(kind, device.id, observation["target"], observation["occurred_at"], {
                "by": by, "property": prop, "from": before["values"].get(prop) if before else None,
                "to": values.get(prop),
            }, epoch=epoch)

    def home_event(self, target, event_type, occurred_at, payload, installation):
        at = offset_time(occurred_at)
        incoming = (target, event_type)
        for rule in installation.home_rules:
            progress = self.sequences.get(rule, [])
            expected = rule.sources[len(progress)]
            if incoming == (expected.target, expected.event_type) and (
                not progress or at >= offset_time(progress[-1])
            ):
                progress = [*progress, occurred_at]
            elif incoming == (rule.sources[0].target, rule.sources[0].event_type):
                progress = [occurred_at]
            if len(progress) != len(rule.sources):
                self.sequences[rule] = progress
                continue
            self.sequences.pop(rule, None)
            detail = {}
            if rule.count_field:
                count = payload.get(rule.count_field)
                if type(count) is not int or count < 1:
                    continue
                detail["count"] = count
            self.emit(rule.event, "hub", target, occurred_at, detail, evidence_from=progress[0])

    def raw_event(self, raw, at, payload, installation):
        self.home_event(raw["target"], raw["event_type"], raw["occurred_at"], payload, installation)
        # Non-state device signals carry no operation correlation or local-operation detection.
        device = next((item for item in installation.devices.devices
                       if installation.bindings[item.id].target == raw["target"]), None)
        if not device or not re.fullmatch(
            rf"{re.escape(device.type)}\.[a-z][a-z0-9_]*", raw["event_type"]
        ):
            return
        if raw["event_type"].endswith(".changed"):
            prop = payload.get("property")
            if not isinstance(prop, str) or not {"from", "to"} <= payload.keys():
                return
            epoch = self.store.get("bindings")[device.id]["epoch"]
            for attempt in self.store.attempts(target=raw["target"]):
                claim = attempt["claims"].get(prop)
                if (claim and claim["owned"] and attempt["epoch"] == epoch
                        and at >= offset_time(attempt["read_back"]["observed_at"])):
                    claim["owned"] = False
                    self.store.save_attempt(attempt)
        self.emit(raw["event_type"], device.id, raw["target"], raw["occurred_at"], {**payload, "by": "unknown"})

    def emit(self, kind, source, target, occurred_at, payload, *, evidence_from=None, epoch=None):
        at = offset_time(occurred_at)
        event = Event(
            event_id=identity("ev"), household_id=self.household, type=kind, source=source,
            at=occurred_at, payload=payload,
        )
        body = wire(event)
        if evidence_from is not None:
            body["evidence_from"] = evidence_from
        if epoch is not None:
            body["epoch"] = epoch
        data = packet(EventBatch([event]), "event_batch.json")
        self.store.fact(target, at.timestamp(), body)
        self.store.queue(event.event_id, "event", "/v1/hub/events", at.timestamp(), data)

    def in_use_by_person(self, observation):
        onset = self.job_starts.get(observation["target"])
        if not onset:
            return False
        if observation["job_id"] is not None:
            return onset["job_id"] == observation["job_id"]
        witness = observation["revisions"].get("in_use")
        return witness is not None and onset["revisions"].get("in_use") == witness


def changed_properties(before, observation, operation):
    values = observation["values"]
    revisions = observation["revisions"]
    if before:
        old_values, old_revisions = before["values"], before["revisions"]
        return sorted(prop for prop in values.keys() | old_values.keys() if (
            prop in revisions and revisions[prop] != old_revisions.get(prop)
            or prop in values and prop in old_values and values[prop] != old_values[prop]
        ))
    if operation:
        return sorted(operation["desired"].keys() & values.keys())
    return list(values) if len(values) == 1 else []
