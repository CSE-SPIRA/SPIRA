"""Independent device effects, readback, and lifecycle transitions."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .profile import Device, Profile
from .storage import WorldStorage, identity

DEVICE_SCHEMA = "spira.device.v1"
SEOUL = ZoneInfo("Asia/Seoul")
PEOPLE = frozenset({"resident", "child", "guest"})
LOCAL_ACTORS = PEOPLE | {"external_automation", "device_self"}
READBACK = frozenset({"current", "stale", "missing", "unavailable"})


def wall_time() -> datetime:
    return datetime.now(SEOUL)


class InvalidMutation(ValueError):
    pass


class World:
    def __init__(
        self, path: Path, profile: Profile, clock: Callable[[], datetime] = wall_time
    ):
        self.profile = profile
        self.devices = {device.target: device for device in profile.devices}
        self.clock = clock
        self.command_faults: dict[str, str] = {}
        self.read_faults: dict[str, tuple[str, dict]] = {}
        self.store = WorldStorage(path)
        try:
            with self.store.transaction():
                self._seed()
        except BaseException:
            self.store.close()
            raise

    def _seed(self):
        if self.store.control("commands_recorded_since") is None:
            self.store.save_control("commands_recorded_since", self.clock().isoformat())
        old_light = self.store.control("legacy_light")
        for target, device in self.devices.items():
            if self.store.state(target) is not None:
                continue
            state = {
                "values": {
                    key: prop.initial for key, prop in device.properties.items()
                },
                "revisions": {key: identity("pr") for key in device.properties},
                "available": device.available and device.substrate == "virtual",
                "occurred_at": self.clock().isoformat(),
                "job_id": None,
                "due": None,
            }
            if (
                old_light
                and self.profile.household_id == "h_042"
                and device.logical_id == "light_01"
                and "power" in device.properties
            ):
                old = json.loads(old_light)
                state["values"]["power"] = old["value"]
                state["revisions"]["power"] = old["witness"]
                state["occurred_at"] = datetime.fromtimestamp(
                    old["at"], SEOUL
                ).isoformat()
            self.store.save_state(target, state)

    @property
    def epoch(self) -> str:
        return self.store.control("world_epoch")

    def _device(self, target: str) -> Device:
        device = self.devices.get(target)
        if device is None:
            raise InvalidMutation("unknown target")
        return device

    def _available(self, device: Device, state: dict) -> bool:
        return device.substrate == "virtual" and state["available"]

    def _discovery(self, device: Device, state: dict) -> dict:
        return {
            "target": device.target,
            "device_type": device.device_type,
            "room": device.room,
            "available": self._available(device, state),
            "substrate": device.substrate,
            "local_operation_reporting": device.local_operation_reporting,
            **({"assumption": device.assumption} if device.assumption else {}),
            "capabilities": {
                "commands": device.commands,
                "properties": list(device.properties),
            },
        }

    def discover(self) -> dict:
        with self.store.lock:
            return {
                "devices": [
                    self._discovery(device, self.store.state(target))
                    for target, device in self.devices.items()
                ]
            }

    def _report(
        self,
        target: str,
        state: dict,
        *,
        observed_at: str,
        available: bool,
        event_type: str | None = None,
        operation_id: str | None = None,
        local_operation: bool = False,
        include_values: bool = True,
    ) -> dict:
        device = self.devices.get(target)
        return {
            "schema": DEVICE_SCHEMA,
            "kind": "state_report",
            "signal_id": identity("sig"),
            "target": target,
            "event_type": event_type,
            "world_revision": state.get("world_revision", self.store.revision),
            "values": state["values"] if include_values else {},
            "revisions": state["revisions"] if include_values else {},
            "occurred_at": state["occurred_at"],
            "observed_at": observed_at,
            "available": available,
            "substrate": device.substrate if device else None,
            "job_id": state["job_id"] if include_values else None,
            "operation_id": operation_id,
            "local_operation": local_operation,
        }

    def _observation(self, target: str) -> tuple[dict, str]:
        now = self.clock().isoformat()
        device = self.devices.get(target)
        state = self.store.state(target) if device else {"occurred_at": now}
        mode, cached = self.read_faults.get(target, ("current", {}))
        available = device is not None and self._available(device, state)
        if not available or mode == "unavailable":
            status = "unavailable"
            report = self._report(
                target, state, observed_at=now, available=False, include_values=False
            )
        elif mode == "stale":
            status = "stale"
            report = self._report(
                target, cached, observed_at=cached["observed_at"], available=True
            )
        else:
            status = mode
            report = self._report(
                target,
                state,
                observed_at=now,
                available=True,
                include_values=mode != "missing",
            )
        return report, status

    def read(self, target: str) -> dict:
        with self.store.lock:
            return self._observation(target)[0]

    def snapshot(self) -> dict:
        with self.store.lock:
            devices = []
            for target, device in self.devices.items():
                report, freshness = self._observation(target)
                devices.append(
                    {
                        **self._discovery(device, self.store.state(target)),
                        **{
                            key: report[key]
                            for key in (
                                "values",
                                "revisions",
                                "available",
                                "occurred_at",
                                "observed_at",
                                "job_id",
                            )
                        },
                        "logical_id": device.logical_id,
                        "label": device.label,
                        "observation": freshness,
                        "qualification": (
                            "virtual_only"
                            if device.substrate == "virtual"
                            else "unqualified"
                        ),
                    }
                )
            return {
                "household_id": self.profile.household_id,
                "world_epoch": self.epoch,
                "world_revision": self.store.revision,
                "devices": devices,
            }

    def _change(
        self,
        device: Device,
        before: dict,
        updates: dict,
        actor: str,
        at: datetime,
        *,
        event_type: str,
        operation_id: str | None = None,
        **state_fields: Any,
    ) -> tuple[dict, list[dict]]:
        after = {
            **before,
            **state_fields,
            "values": {**before["values"], **updates},
            "revisions": {
                **before["revisions"],
                **{key: identity("pr") for key in updates},
            },
            "occurred_at": at.isoformat(),
        }
        self._record(device, actor, event_type, before, after)
        self.store.save_state(device.target, after)
        signals = []
        if self._available(device, after) and device.target not in self.read_faults:
            signals.append(
                self._report(
                    device.target,
                    after,
                    observed_at=at.isoformat(),
                    available=True,
                    event_type=event_type,
                    operation_id=operation_id,
                    local_operation=device.local_operation_reporting
                    and actor in PEOPLE,
                )
            )
        return after, signals

    def _record(
        self, device: Device, actor: str, event_type: str, before: dict, after: dict
    ):
        return self.store.append_truth(
            {
                "actor": actor,
                "logical_id": device.logical_id,
                "target": device.target,
                "event_type": event_type,
                "occurred_at": after["occurred_at"],
                "before": before["values"],
                "after": after["values"],
                "job_id": after["job_id"],
            }
        )

    def _validation(
        self, device: Device, values: dict, *, local: bool = False
    ) -> str | None:
        if (
            not local
            and device.prohibited_properties
            and set(values).intersection(device.prohibited_properties)
        ):
            return "PROHIBITED"
        for key, value in values.items():
            prop = device.properties.get(key)
            if prop is None or not (prop.local_write if local else prop.hub_write):
                return "UNSUPPORTED"
            if not prop.accepts(value):
                return "REJECTED"
        return None if values else "REJECTED"

    def command(
        self, operation_id: str, target: str, desired: dict, expected: dict
    ) -> tuple[dict, list[dict]]:
        with self.store.transaction():
            old_receipt = self.store.receipt(operation_id)
            if old_receipt is not None:
                return old_receipt, []
            self.store.record_command(
                operation_id,
                target,
                self.clock(),
                is_notice=desired.keys() == {"show_notice"},
            )
            status, job_id, signals = self._apply_command(
                operation_id, target, desired, expected
            )
            receipt = {"status": status, "operation_id": operation_id, "job_id": job_id}
            self.store.save_receipt(operation_id, receipt)
            return receipt, signals

    def mark_commands(self) -> dict:
        with self.store.transaction():
            return self.store.mark_commands(self.clock())

    def command_counts(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> dict | None:
        with self.store.lock:
            if start is None:
                saved = self.store.control("command_marker")
                if saved is None:
                    return None
                marker = json.loads(saved)
                counts = self.store.count_commands(after=marker["sequence"])
                window = {"start": marker["at"], "end": self.clock().isoformat()}
            else:
                counts = self.store.count_commands(start=start, end=end)
                window = {"start": start.isoformat(), "end": end.isoformat()}
            total = {
                key: sum(device[key] for device in counts.values())
                for key in ("notices", "other_commands")
            }
            by_device = {
                device.logical_id: counts.pop(
                    device.target, {"notices": 0, "other_commands": 0}
                )
                for device in self.devices.values()
            }
            return {
                "window": window,
                "recording_since": self.store.control("commands_recorded_since"),
                "total": total,
                "by_device": by_device,
                "unbound_targets": counts,
            }

    def _apply_command(
        self, operation_id: str, target: str, desired: dict, expected: dict
    ):
        device = self.devices.get(target)
        if device is None:
            return "UNSUPPORTED", None, []
        state = self.store.state(target)
        if not self._available(device, state):
            return "UNAVAILABLE", None, []
        status = self._validation(device, desired)
        if status:
            return status, None, []
        if any(
            state["revisions"].get(key) != witness for key, witness in expected.items()
        ):
            return "CONFLICT", None, []
        trigger = device.job.trigger_property if device.job else None
        if (
            trigger in desired
            and desired[trigger] is None
            and state["due"]
            and trigger not in expected
        ):
            return "CONFLICT", None, []

        fault = self.command_faults.pop(target, None)
        if fault == "reject":
            return "REJECTED", None, []
        if fault == "unchanged":
            return "ACCEPTED", None, []
        if (
            all(state["values"][key] == value for key, value in desired.items())
            and trigger not in desired
        ):
            return "ACCEPTED", None, []

        job_id, signals = self._effect(device, state, desired, "spira", operation_id)
        return "ACCEPTED", job_id, signals

    def _effect(
        self,
        device: Device,
        state: dict,
        updates: dict,
        actor: str,
        operation_id: str | None = None,
        *,
        start: bool = False,
    ) -> tuple[str | None, list[dict]]:
        at = self.clock()
        trigger = device.job.trigger_property if device.job else None
        event_type = f"{device.device_type}.changed"
        if len(updates) == 1:
            prop = device.properties[next(iter(updates))]
            event_type = prop.event_type or event_type
        job_fields = {}
        job_id = None
        if start or (trigger in updates and updates[trigger] is not None):
            job_id = identity("job")
            duration = device.job.duration_seconds
            if device.job.minutes_property:
                preset = state["values"][device.job.minutes_property]
                if isinstance(preset, dict) and "minutes" in preset:
                    duration = preset["minutes"] * 60
            job_fields = {
                "job_id": job_id,
                "due": (at + timedelta(seconds=duration)).isoformat(),
            }
            updates = {**updates, "in_use": True, "job_status": "running"}
            event_type = f"{device.device_type}.started"
        elif trigger in updates and state["due"]:
            job_fields = {"due": None}
            updates = {**updates, "in_use": False, "job_status": "stopped"}
            event_type = f"{device.device_type}.stopped"
        _, signals = self._change(
            device,
            state,
            updates,
            actor,
            at,
            event_type=event_type,
            operation_id=operation_id,
            **job_fields,
        )
        return job_id, signals

    def local_change(
        self, target: str, actor: str, values: dict, *, start: bool = False
    ) -> list[dict]:
        if actor not in LOCAL_ACTORS:
            raise InvalidMutation("unknown local actor")
        with self.store.transaction():
            device = self._device(target)
            if device.substrate != "virtual":
                raise InvalidMutation("physical control is unavailable")
            state = self.store.state(target)
            if start and (
                not device.job or device.job.trigger_property is not None or values
            ):
                raise InvalidMutation("this device has no separate local start")
            status = self._validation(device, values, local=True) if not start else None
            if status:
                raise InvalidMutation(status)
            return self._effect(device, state, values, actor, start=start)[1]

    def home_event(self, action: str) -> list[dict]:
        facts = self.profile.home_signals.get(action)
        if not facts:
            raise InvalidMutation("unknown home observation")
        with self.store.transaction():
            at = self.clock().isoformat()
            signals = []
            for fact in facts:
                self.store.append_truth(
                    {
                        "actor": "device_self",
                        "logical_id": None,
                        "target": fact.target,
                        "event_type": fact.event_type,
                        "occurred_at": at,
                        "before": None,
                        "after": fact.payload,
                    }
                )
                signals.append(
                    {
                        "schema": DEVICE_SCHEMA,
                        "kind": "event_signal",
                        "signal_id": identity("sig"),
                        "target": fact.target,
                        "event_type": fact.event_type,
                        "occurred_at": at,
                        "payload": fact.payload,
                    }
                )
            return signals

    def complete_due(self) -> list[dict]:
        with self.store.transaction():
            now = self.clock()
            signals = []
            for device in self.devices.values():
                if device.job is None or device.substrate != "virtual":
                    continue
                current = self.store.state(device.target)
                if (
                    current["job_id"]
                    and current["values"]["job_status"] == "running"
                    and current["due"]
                    and datetime.fromisoformat(current["due"]) <= now
                ):
                    # The due time belongs to the current job row, overwritten on replacement.
                    _, pushed = self._change(
                        device,
                        current,
                        {"in_use": False, "job_status": "completed"},
                        "device_self",
                        now,
                        event_type=f"{device.device_type}.completed",
                        due=None,
                    )
                    signals.extend(pushed)
            return signals

    def set_fault(self, target: str, fault: str, mode: str) -> list[dict]:
        with self.store.transaction():
            device = self._device(target)
            state = self.store.state(target)
            if device.substrate != "virtual":
                raise InvalidMutation("physical control is unavailable")
            if fault == "link" and mode in {"online", "offline"}:
                available = mode == "online"
                if available == state["available"]:
                    return []
                at = self.clock().isoformat()
                after = {**state, "available": available, "occurred_at": at}
                self._record(
                    device,
                    "device_self",
                    f"{device.device_type}.availability",
                    state,
                    after,
                )
                self.store.save_state(target, after)
                return [self._observation(target)[0]]
            if fault == "command" and mode in {"clear", "reject", "unchanged"}:
                if mode == "clear":
                    self.command_faults.pop(target, None)
                else:
                    self.command_faults[target] = mode
                return []
            if fault == "readback" and mode in READBACK:
                if mode == "current":
                    self.read_faults.pop(target, None)
                else:
                    self.read_faults[target] = (
                        mode,
                        {
                            **state,
                            "observed_at": self.clock().isoformat(),
                            "world_revision": self.store.revision,
                        },
                    )
                return []
            raise InvalidMutation("unknown fault mode")
