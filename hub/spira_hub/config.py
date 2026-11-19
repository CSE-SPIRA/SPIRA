"""Local installation configuration. Discovery alone grants no authority."""

import json
from dataclasses import dataclass
from pathlib import Path

from spira_contracts.common import HomeEvent
from spira_contracts.devices import Devices

from .contracts import read_model, wire


@dataclass(frozen=True)
class Binding:
    target: str
    native_identity: str
    commands: dict

    def desired(self, action):
        mapping = self.commands.get(action.cmd)
        if mapping is None:
            return None
        if isinstance(mapping, str):
            return {mapping: action.value}
        if "properties" in mapping:
            return {target: action.value[name] for name, target in mapping["properties"].items()}
        return mapping["fixed"].copy()


@dataclass(frozen=True)
class Source:
    target: str
    event_type: str


@dataclass(frozen=True)
class HomeRule:
    event: str
    sources: tuple[Source, ...]
    count_field: str | None


@dataclass(frozen=True)
class Installation:
    devices: Devices
    bindings: dict[str, Binding]
    home_rules: tuple[HomeRule, ...]

    @property
    def delegates(self):
        return {device.id: device for device in self.devices.devices}

    @classmethod
    def load(cls, path: Path, household: str):
        raw = json.loads(path.read_text(encoding="utf-8"))
        devices = read_model(Devices, raw["devices"], "devices.json")
        if devices.household_id != household:
            raise ValueError("Installation and Server household must match")
        bindings = {}
        targets = set()
        ids = set()
        for device in devices.devices:
            if device.id in ids or any(command.cmd in device.never for command in device.commands):
                raise ValueError("Duplicate device or prohibited delegated command")
            ids.add(device.id)
            binding = raw["bindings"][device.id]
            target = binding["target"]
            native_identity = binding.get("native_identity", target)
            if not isinstance(target, str) or not target or target in targets:
                raise ValueError("Each device needs a unique native target")
            if not isinstance(native_identity, str) or not native_identity:
                raise ValueError("Invalid native identity")
            targets.add(target)
            commands = binding.get("commands", {})
            delegated = {command.cmd: command for command in device.commands}
            if len(delegated) != len(device.commands) or commands.keys() - delegated.keys():
                raise ValueError("Command bindings must refer to unique delegated commands")
            for name, mapping in commands.items():
                check_mapping(mapping, delegated[name].value_schema)
            bindings[device.id] = Binding(target, native_identity, commands)

        rules = []
        for item in raw.get("home_signals", []):
            sources = tuple(Source(**source) for source in item["sources"])
            if not sources or any(not source.target or not source.event_type for source in sources):
                raise ValueError("Home rules need explicitly bound sources")
            rules.append(HomeRule(HomeEvent(item["event"]).value, sources, item.get("count_field")))
        return cls(devices, bindings, tuple(rules))

    def projection(self):
        return wire(self.devices)["devices"]


def check_mapping(mapping, schema):
    if isinstance(mapping, str) and mapping and schema is not None:
        return
    if not isinstance(mapping, dict) or len(mapping) != 1:
        raise ValueError("Invalid command-to-property mapping")
    fixed = mapping.get("fixed")
    if isinstance(fixed, dict) and fixed and schema is None:
        return
    properties = mapping.get("properties")
    if (isinstance(properties, dict) and isinstance(schema, dict)
            and properties.keys() == schema.keys()
            and all(isinstance(name, str) and name for name in properties.values())
            and len(set(properties.values())) == len(properties)):
        return
    raise ValueError("Command mapping does not cover its delegated value schema")
