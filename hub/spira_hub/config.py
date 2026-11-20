"""Local installation configuration. Discovery alone grants no authority."""

import json
from dataclasses import dataclass
from pathlib import Path

from spira_contracts.common import HomeEvent
from spira_contracts.devices import Device, Devices

from .contracts import read_model, wire

SIMULATOR_MAPPINGS = {
    "cleaner": {"clean": "clean"},
    "display": {"play_mood": "play_mood", "off": {"fixed": {"play_mood": None}}},
    "cooktop": {"child_lock": {"fixed": {"child_lock": True}}},
    "oven": {"set_cook_standby": "preset"},
    "fridge": {"show_notice": "show_notice", "clear_notice": {"fixed": {"show_notice": None}}},
    "purifier": {"mode": {"properties": {"mode": "mode"}},
                 "wind_strength": {"properties": {"wind_strength": "wind_strength"}}},
    "dishwasher": {"set_course_standby": {"properties": {"course": "course"}},
                   "delayed_start": {"properties": {"hours": "delay_hours"}}},
    "washer": {"set_course_standby": {"properties": {"course": "course"}}},
    "speaker": {"play": "play", "stop": {"fixed": {"play": None}}},
}


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
    lg_account_devices: frozenset[str]

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
        lg_account_devices = raw.get("lg_account_devices", [])
        if not isinstance(lg_account_devices, list) or not all(
            isinstance(device_id, str) and device_id in ids for device_id in lg_account_devices
        ):
            raise ValueError("LG installation entries must name configured devices")
        return cls(devices, bindings, tuple(rules), frozenset(lg_account_devices))

    def projection(self):
        return wire(self.devices)["devices"]

    def with_onboarding(self, records):
        devices = self.delegates
        bindings = self.bindings.copy()
        for device_id, record in records.items():
            base = devices.get(device_id)
            if record["source"] == "installation":
                if base is None:
                    continue
                offered = {command.cmd: command for command in base.commands}
                settings = record["settings"]
                commands = [offered[cmd] for cmd in settings["delegated_commands"] if cmd in offered]
                device = with_settings(base, settings, commands)
            else:
                device = Device.model_validate(record["device"])
                configured = base is not None and base.type == device.type
                if configured:
                    device = device.model_copy(update={
                        "substrate": base.substrate, "events": base.events, "noisy": base.noisy,
                    })
                target = bindings[device_id].target if configured else f"mqtt:{device_id}"
                template = bindings[device_id] if configured else Binding(target, target, {})
                defaults = SIMULATOR_MAPPINGS.get(device.type, {})
                mappings = {}
                for command in device.commands:
                    mapping = template.commands.get(command.cmd, defaults.get(command.cmd))
                    if mapping is None:
                        continue
                    try:
                        check_mapping(mapping, command.value_schema)
                    except ValueError:
                        # The account can offer a schema the installed adapter cannot execute.
                        continue
                    mappings[command.cmd] = mapping
                bindings[device_id] = Binding(template.target, template.native_identity, mappings)
            devices[device_id] = device
        if len({binding.target for binding in bindings.values()}) != len(bindings):
            raise ValueError("Each device needs a unique native target")
        return Installation(self.devices.model_copy(update={"devices": list(devices.values())}),
                            bindings, self.home_rules, self.lg_account_devices)


def with_settings(device, settings, commands):
    fields = {"room": settings["room"], "commands": commands}
    if settings["label"] is not None:
        return device.model_copy(update={**fields, "label": settings["label"]})
    # A local null label is the absence of the optional C-2 label.
    body = device.model_dump(exclude={"label"})
    return Device.model_validate({**body, **fields})


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
