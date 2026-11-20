"""Hub-owned home-network onboarding and the test LG account client."""

from dataclasses import dataclass
from secrets import compare_digest
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, TypeAdapter
from spira_contracts.devices import Command, Device
from spira_contracts.devices_response import DevicesResponse
from spira_contracts.error import Error

from .config import with_settings
from .contracts import read_model, wire
from .runtime import IO_FAILURES

PATH = "/home/onboarding/devices"


class LGCommand(Command):
    basis: Literal["sdk", "lg_assumed"] | None = None


class LGDevice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    type: str
    label: str | None
    commands: list[LGCommand]
    never: list[str]


LG_DEVICES = TypeAdapter(list[LGDevice])


class DeviceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    room: str | None
    label: str | None
    delegated_commands: list[str]


class SettingsBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    devices: list[DeviceSettings]


@dataclass(frozen=True)
class Candidate:
    device: Device
    source: str
    bases: dict

    def view(self, stored):
        device = self.device
        return {
            "id": device.id, "type": device.type, "label": device.label, "room": device.room,
            "source": self.source, "never": device.never,
            "commands": [
                {"cmd": command.cmd, "value_schema": wire(command).get("value_schema"),
                 "basis": self.bases.get(command.cmd)}
                for command in device.commands
            ],
            "stored": {
                "room": stored.room if stored else None,
                "label": stored.label if stored else None,
                "delegated_commands": [command.cmd for command in stored.commands] if stored else [],
            },
        }


async def discover_lg(http):
    response = await http.get("/lg/devices")
    response.raise_for_status()
    found = {}
    for candidate in LG_DEVICES.validate_python(response.json()):
        commands = [
            command.model_dump(mode="json", exclude={"basis"}, exclude_none=True)
            for command in candidate.commands
        ]
        bases = {command.cmd: command.basis for command in candidate.commands}
        if candidate.id in found or len(bases) != len(commands):
            raise ValueError("Duplicate device or command in LG discovery")
        label = {"label": candidate.label} if candidate.label is not None else {}
        device = read_model(Device, {
            "id": candidate.id, "type": candidate.type, "room": None, **label,
            "substrate": "virtual", "commands": commands, "never": candidate.never,
            "events": [], "noisy": False,
        }, "devices.json#/$defs/Device")
        found[device.id] = Candidate(device, "lg_account", bases)
    return found


def candidates_for(installation, lg):
    candidates = dict(lg)
    for device in installation.devices.devices:
        if device.id in candidates or device.id in installation.lg_account_devices:
            continue
        basis = "standard" if device.type in ("light", "smart_plug") else None
        candidates[device.id] = Candidate(device, "installation", {c.cmd: basis for c in device.commands})
    return candidates


def update_records(candidates, records, batch):
    records = records.copy()
    ids = set()
    for row in batch.devices:
        candidate = candidates.get(row.id)
        if candidate is None or row.id in ids:
            raise ValueError("Each device must be a distinct onboarding candidate")
        ids.add(row.id)
        device = candidate.device
        offered = {command.cmd: command for command in device.commands}
        names = row.delegated_commands
        if len(set(names)) != len(names) or any(name not in offered or name in device.never for name in names):
            raise ValueError("Every delegated command must be distinct, offered, and allowed")
        settings = row.model_dump(exclude={"id"})
        record = {"source": candidate.source}
        if candidate.source == "lg_account":
            record["device"] = wire(with_settings(device, settings, [offered[name] for name in names]))
        else:
            record["settings"] = settings
        records[row.id] = record
    return records


class OnboardingError(Exception):
    def __init__(self, status, code, message):
        self.status = status
        self.body = Error(code=code, message=message)


def add_onboarding(app, runtime, *, hub_key, lg_http):
    async def authorize(request: Request):
        supplied = request.headers.get("X-API-Key", "")
        if not hub_key or not compare_digest(supplied.encode(), hub_key.encode()):
            raise OnboardingError(401, "unauthorized", "Household Hub key required")

    @app.exception_handler(OnboardingError)
    async def onboarding_error(_request, error):
        return JSONResponse(wire(error.body), status_code=error.status)

    router = APIRouter(dependencies=[Depends(authorize)])

    async def load_lg():
        if lg_http is None:
            raise OnboardingError(503, "internal", "LG device discovery is not configured")
        try:
            return await discover_lg(lg_http)
        except IO_FAILURES:
            raise OnboardingError(502, "internal", "LG device discovery failed") from None

    def load_candidates(lg):
        runtime.reload_installation()
        if runtime.config_error:
            raise OnboardingError(503, "internal", "Hub installation is unavailable")
        return candidates_for(runtime.configured, lg)

    @router.get(PATH)
    async def get_devices():
        candidates = load_candidates(await load_lg())
        stored = runtime.installation.delegates
        return {"devices": [candidate.view(stored.get(device_id))
                            for device_id, candidate in candidates.items()]}

    @router.put(PATH)
    async def put_devices(request: Request):
        try:
            batch = SettingsBatch.model_validate(await request.json())
        except ValueError:
            raise OnboardingError(422, "validation_error", "Invalid device settings body") from None
        lg = await load_lg()
        async with runtime.pull_lock:
            candidates = load_candidates(lg)
            try:
                records = update_records(candidates, runtime.store.get("onboarding", {}), batch)
                installation = runtime.configured.with_onboarding(records)
            except ValueError as error:
                raise OnboardingError(422, "validation_error", str(error)) from None
            try:
                revision = await runtime.save_onboarding(records, installation)
            except IO_FAILURES:
                raise OnboardingError(502, "internal", "Could not prepare the device revision") from None
        if revision is None:
            raise OnboardingError(502, "internal", "Device settings saved; Server upload pending")
        return wire(DevicesResponse(revision=revision))

    app.include_router(router)
