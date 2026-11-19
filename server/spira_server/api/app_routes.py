"""App routes (contracts/openapi/app.yaml). This batch: POST /v1/orders. The rest come with S6."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from .. import clock
from ..config import get_config
from ..pipeline import s1_extract
from ..store.images import image_kind
from .auth import require_app
from .errors import ApiError

router = APIRouter(dependencies=[Depends(require_app)])

HOUSEHOLD_ID = re.compile(r"^h_[0-9a-z]+$")


@router.post("/v1/orders")
async def post_orders(
    household_id: str = Form(...),
    images: list[UploadFile] | None = File(None),
    shared_at: str | None = Form(None),
    source_id: str | None = Form(None),
) -> JSONResponse:
    if not HOUSEHOLD_ID.match(household_id):
        raise ApiError("validation_error", "household_id has the wrong format.", {"path": "household_id"})
    when = None
    if shared_at:
        try:
            when = clock.parse(shared_at)
        except ValueError:
            raise ApiError("validation_error", "shared_at needs ISO 8601 with offset.", {"path": "shared_at"}) from None

    n = get_config().numbers
    files = images or []
    if not 1 <= len(files) <= n.images_per_request:
        raise ApiError("invalid_image", f"Send 1 to {n.images_per_request} images.")
    payloads = []
    for f in files:
        data = await f.read()
        if len(data) > n.image_max_mb * 1024 * 1024:
            raise ApiError("invalid_image", f"Each image must be {n.image_max_mb} MB or smaller.")
        if image_kind(data) is None:
            raise ApiError("invalid_image", "Images must be jpg or png.")
        payloads.append(data)

    try:
        accepted = s1_extract.receive_capture(household_id, payloads, when, source_id or None)
    except s1_extract.UnknownHousehold:
        raise ApiError("not_found", "Unknown household.") from None
    body = {"episode_id": accepted.episode_id, "status": accepted.status}
    return JSONResponse(body, status_code=200 if accepted.duplicate else 202)
