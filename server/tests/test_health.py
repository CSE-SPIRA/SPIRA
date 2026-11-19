"""T1: /health is 503 until the DB and the embedding model are ready, then 200 {"status": "ok"}."""

from fastapi.testclient import TestClient
from spira_contracts.validate import validate

from spira_server.kb import embedding
from spira_server.main import create_app


def test_health_503_then_200():
    embedding.reset()
    client = TestClient(create_app(start_background=False))
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "db": True, "embedding": False}
    validate(r.json(), "health.json")

    embedding.warm_up()
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    validate(r.json(), "health.json")


def test_health_needs_no_auth_and_lifespan_loads_mock_model():
    embedding.reset()
    with TestClient(create_app(start_background=False)) as client:
        assert client.get("/health").status_code == 200
