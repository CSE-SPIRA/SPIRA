"""Inbound JSON bodies (spec §2.1, §12.1): parsed with the generated model, then checked with
`spira_contracts.validate` for rules the models cannot express. Either failure -> 422 validation_error with
details.path. Routes get the raw dict (the shape the contract defines)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import Depends, Request
from pydantic import BaseModel, ValidationError
from spira_contracts.validate import errors

from .errors import ApiError, loc_path

_INDEX = re.compile(r"^\d+$")


def slash_path(path: str) -> str:
    """'devices/0/never' -> 'devices[0].never' (the format of error.json details.path)."""
    if path in ("", "(root)"):
        return "(root)"
    out = ""
    for p in path.split("/"):
        out += f"[{p}]" if _INDEX.match(p) else (f".{p}" if out else p)
    return out


def check(raw: Any, model: type[BaseModel], schema: str) -> dict:
    try:
        model.model_validate(raw)
    except ValidationError as e:
        first = e.errors()[0]
        raise ApiError("validation_error", "Request does not match the schema.",
                       {"path": loc_path(tuple(first.get("loc", ()))), "reason": first.get("msg", "")}) from None
    found = errors(raw, schema)
    if found:
        path, _, reason = found[0].partition(": ")
        raise ApiError("validation_error", "Request does not match the schema.",
                       {"path": slash_path(path), "reason": reason})
    return raw


def body(model: type[BaseModel], schema: str):
    """Route parameter: `data: dict = body(Devices, "devices.json")`. Declare it after the auth dependency so a
    missing key is 401 before a bad body is 422."""
    async def _read(request: Request) -> dict:
        try:
            raw = await request.json()
        except ValueError:
            raise ApiError("validation_error", "Body is not JSON.", {"path": "(root)"}) from None
        return check(raw, model, schema)
    return Depends(_read)
