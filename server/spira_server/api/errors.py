"""Error bodies (spec §12.1, contracts/schemas/error.json): every 4xx/5xx is {code, message, details?}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

STATUS = {
    "invalid_request": 400,
    "invalid_image": 400,
    "unauthorized": 401,
    "forbidden": 403,
    "not_found": 404,
    "line_started": 409,
    "stale_revision": 409,
    "validation_error": 422,
    "household_types_invalid": 422,
    "internal": 500,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        if code not in STATUS:
            raise ValueError(f"unknown error code {code}")
        self.code, self.message, self.details = code, message, details

    @property
    def status(self) -> int:
        return STATUS[self.code]


def body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "message": message}
    if details:
        out["details"] = details
    return out


def loc_path(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "form")]
    out = ""
    for p in parts:
        out += f"[{p}]" if p.isdigit() else (f".{p}" if out else p)
    return out or "(root)"


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {"loc": (), "msg": "invalid"}
        return JSONResponse(
            body("validation_error", "Request does not match the schema.",
                 {"path": loc_path(tuple(first.get("loc", ()))), "reason": first.get("msg", "")}),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "invalid_request"}.get(
            exc.status_code, "invalid_request" if exc.status_code < 500 else "internal")
        return JSONResponse(body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _internal(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(body("internal", "Internal error."), status_code=500)
