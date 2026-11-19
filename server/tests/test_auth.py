"""T41 (app part): app routes need the Bearer token; errors follow error.json."""

from fastapi import Depends
from fastapi.testclient import TestClient
from spira_contracts.validate import validate

from spira_server.api.auth import hub_key_hash, new_hub_key, require_app
from spira_server.main import create_app


def _client() -> TestClient:
    app = create_app(start_background=False)

    @app.get("/v1/ping", dependencies=[Depends(require_app)])
    def ping() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_missing_or_wrong_token_is_401(app_headers):
    c = _client()
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic test-app-token"}):
        r = c.get("/v1/ping", headers=headers)
        assert r.status_code == 401
        assert r.json()["code"] == "unauthorized"
        validate(r.json(), "error.json")
    assert c.get("/v1/ping", headers=app_headers).json() == {"ok": True}


def test_unknown_route_is_error_body():
    r = _client().get("/v1/nothing")
    assert r.status_code == 404
    validate(r.json(), "error.json")


def test_hub_key_shape():
    key, digest = new_hub_key()
    assert key.startswith("hk_") and len(key) == 67
    assert digest == hub_key_hash(key) and len(digest) == 64
