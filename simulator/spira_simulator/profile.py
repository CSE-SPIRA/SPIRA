"""Load the Simulator's native device and sensor configuration."""

import json
import math
import re
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

PRIVATE_FIELDS = frozenset({"actor", "ground_truth_actor", "provenance", "by"})


def public_value(value: Any) -> bool:
    if isinstance(value, dict):
        return not PRIVATE_FIELDS.intersection(value) and all(
            map(public_value, value.values())
        )
    if isinstance(value, list):
        return all(map(public_value, value))
    if isinstance(value, float):
        return math.isfinite(value)
    return True


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Property(ProfileModel):
    initial: Any
    schema_: dict[str, Any] = Field(alias="schema")
    hub_write: bool = True
    local_write: bool = True
    event_type: str | None = None

    @model_validator(mode="after")
    def check_initial(self):
        Draft202012Validator.check_schema(self.schema_)
        if not self.accepts(self.initial):
            raise ValueError("invalid initial property value")
        return self

    def accepts(self, value: Any) -> bool:
        return public_value(value) and Draft202012Validator(self.schema_).is_valid(
            value
        )


class Job(ProfileModel):
    duration_seconds: float = Field(gt=0)
    trigger_property: str | None = None
    minutes_property: str | None = None


class Device(ProfileModel):
    target: str = Field(min_length=1)
    logical_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    device_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    room: str = Field(min_length=1)
    label: str | None = None
    substrate: Literal["virtual", "physical"]
    available: bool
    local_operation_reporting: bool
    assumption: str | None = None
    commands: list[str]
    properties: dict[str, Property] = Field(min_length=1)
    job: Job | None = None
    prohibited_properties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_capability(self):
        if self.local_operation_reporting and not self.assumption:
            raise ValueError("Class A requires a displayed assumption")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", key) for key in self.properties):
            raise ValueError("invalid property name")
        if PRIVATE_FIELDS.intersection(self.properties):
            raise ValueError("private fields cannot be device properties")
        if self.job:
            keys = {
                "in_use",
                "job_status",
                self.job.trigger_property,
                self.job.minutes_property,
            }
            if not keys.difference({None}).issubset(self.properties):
                raise ValueError("job refers to undeclared properties")
            if (
                self.properties["in_use"].initial is not False
                or self.properties["job_status"].initial != "idle"
            ):
                raise ValueError("jobs must start idle")
            for key in ("in_use", "job_status"):
                if self.properties[key].hub_write or self.properties[key].local_write:
                    raise ValueError(f"{key} is maintained by the job lifecycle")
        return self


class SensorFact(ProfileModel):
    target: str = Field(min_length=1)
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
    payload: dict[str, Any]

    @model_validator(mode="after")
    def check_payload(self):
        if not public_value(self.payload):
            raise ValueError("sensor payload contains private fields")
        return self


class Profile(ProfileModel):
    household_id: str = Field(pattern=r"^h_[0-9a-z]+$")
    devices: list[Device]
    home_signals: dict[str, list[SensorFact]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_devices(self):
        for attribute in ("target", "logical_id"):
            if len({getattr(device, attribute) for device in self.devices}) != len(
                self.devices
            ):
                raise ValueError(f"duplicate device {attribute}")
        return self


DEFAULT_PROFILE = Path(__file__).parent / "profiles" / "ep_9031.json"


def load_profile(path: Path = DEFAULT_PROFILE) -> Profile:
    return Profile.model_validate(json.loads(path.read_text(encoding="utf-8")))
