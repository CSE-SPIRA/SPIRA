import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from spira_contracts.validate import validate

from hub.spira_hub.dashboard import create_app
from hub.spira_hub.runtime import Runtime
from hub.spira_hub.store import Store

PATH = "/home/onboarding/devices"
HEADERS = {"X-API-Key": "test-home-key"}
INSTALLATION = Path(__file__).resolve().parents[2] / "installation.example.json"


@pytest.fixture
def home(tmp_path):
    configured = json.loads(INSTALLATION.read_text(encoding="utf-8"))
    idle = configured["devices"]["devices"][0]
    idle.update(commands=[], room=None)
    configured["bindings"][idle["id"]]["commands"] = {}
    path = tmp_path / "installation.json"
    path.write_text(json.dumps(configured), encoding="utf-8")
    household = configured["devices"]["household_id"]
    store = Store(tmp_path / "hub.db", household)
    try:
        runtime = Runtime(store, SimpleNamespace(household=household), SimpleNamespace(), path)
        with TestClient(create_app(runtime, hub_key=HEADERS["X-API-Key"])) as client:
            yield client, runtime, configured
    finally:
        store.db.close()


def test_home_devices_returns_full_installed_list_before_discovery_or_plans(home):
    client, _, configured = home
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    validate(response.json(), "devices.json")
    assert response.json() == configured["devices"]
    assert client.put(PATH, headers=HEADERS).status_code == 405


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_home_devices_rejects_missing_or_wrong_key(home, headers):
    client, _, _ = home
    response = client.get(PATH, headers=headers)
    assert response.status_code == 401
    validate(response.json(), "error.json")
    assert response.json()["code"] == "unauthorized"


def test_home_devices_uses_reloaded_installation(home):
    client, runtime, configured = home
    path = runtime.installation_path
    path.write_text("{}", encoding="utf-8")
    runtime.reload_installation()
    unavailable = client.get(PATH, headers=HEADERS)
    assert unavailable.status_code == 503
    validate(unavailable.json(), "error.json")

    configured["devices"]["devices"][0]["room"] = "Home office"
    path.write_text(json.dumps(configured), encoding="utf-8")
    runtime.reload_installation()
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == configured["devices"]
