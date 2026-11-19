"""Auth (spec §12.1). App routes: Bearer APP_DEMO_TOKEN. Hub routes: X-API-Key -> household by key hash, then every
household the request names must be that one (403)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Header
from sqlalchemy import select

from ..db.engine import session_scope
from ..db.models import Household
from ..settings import get_settings
from .errors import ApiError


def require_app(authorization: str | None = Header(default=None)) -> None:
    token = get_settings().app_demo_token
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value or not hmac.compare_digest(value.encode(), token.encode()):
        raise ApiError("unauthorized", "Missing or wrong app token.")


def require_hub(x_api_key: str | None = Header(default=None)) -> str:
    """The household id of the key (401 when missing or unknown)."""
    if not x_api_key:
        raise ApiError("unauthorized", "Missing hub key.")
    with session_scope() as s:
        hid = s.execute(select(Household.id).where(Household.hub_key_hash == hub_key_hash(x_api_key))
                        ).scalar_one_or_none()
    if hid is None:
        raise ApiError("unauthorized", "Unknown hub key.")
    return hid


def same_household(key_household: str, named: str | None) -> None:
    if named != key_household:
        raise ApiError("forbidden", "This key belongs to another household.")


def new_hub_key() -> tuple[str, str]:
    """(key shown once, SHA-256 hex stored) — `hk_` + 64 hex (D3)."""
    key = "hk_" + secrets.token_hex(32)
    return key, hub_key_hash(key)


def hub_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
