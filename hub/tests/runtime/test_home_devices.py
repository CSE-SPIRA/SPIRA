import pytest
from fastapi.testclient import TestClient

from hub.spira_hub.dashboard import create_app


@pytest.mark.parametrize("method", ["GET", "PUT", "POST"])
def test_dashboard_does_not_expose_home_onboarding_devices(method):
    with TestClient(create_app(object())) as client:
        response = client.request(method, "/home/onboarding/devices", headers={"X-API-Key": "test-key"})
    assert response.status_code == 404
