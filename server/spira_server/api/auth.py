"""Auth (spec §12.1). App routes: Bearer APP_DEMO_TOKEN. Hub routes (X-API-Key) come with the S6 hub API."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Header

from ..settings import get_settings
from .errors import ApiError


def require_app(authorization: str | None = Header(default=None)) -> None:
    token = get_settings().app_demo_token
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value or not hmac.compare_digest(value.encode(), token.encode()):
        raise ApiError("unauthorized", "Missing or wrong app token.")


def new_hub_key() -> tuple[str, str]:
    """(key shown once, SHA-256 hex stored) — `hk_` + 64 hex (D3)."""
    key = "hk_" + secrets.token_hex(32)
    return key, hub_key_hash(key)


def hub_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
