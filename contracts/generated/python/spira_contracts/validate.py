"""Validate a payload against a contracts schema (copied into the package by codegen/generate.sh).

    from spira_contracts.validate import validate, errors
    validate(plan_dict, "plan.json")        # raises ContractError
    errors(event_list, "event_batch.json")  # -> list of "path: message"

Use it in tests, or at the edge of a part, for rules pydantic models do not express
(e.g. payload.by required for device events, reason required when blocked).
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


class ContractError(ValueError):
    pass


@lru_cache(maxsize=1)
def _registry() -> Registry:
    data = resources.files(__package__) / "data"
    pairs = []
    for f in data.iterdir():
        if f.name.endswith(".json") and f.name != "enums.json":
            pairs.append((f.name, Resource.from_contents(json.loads(f.read_text(encoding="utf-8")))))
    return Registry().with_resources(pairs)


def errors(payload, schema: str) -> list[str]:
    v = Draft202012Validator({"$ref": schema}, registry=_registry())
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in v.iter_errors(payload)]


def validate(payload, schema: str) -> None:
    found = errors(payload, schema)
    if found:
        raise ContractError(f"{schema}: " + "; ".join(found[:5]))


def enums() -> dict:
    """enums.json as a dict (values for display or checks)."""
    return json.loads((resources.files(__package__) / "data" / "enums.json").read_text(encoding="utf-8"))
