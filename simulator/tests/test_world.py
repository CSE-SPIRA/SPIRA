import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from spira_simulator.api import create_app
from spira_simulator.storage import UnsupportedSchema, WorldStorage


def light(snapshot):
    return next(device for device in snapshot["devices"] if device["target"] == "sim_light_01")


def test_sim_at01_02_03_independent_state_journal_and_restart(tmp_path):
    path = tmp_path / "world.db"
    with TestClient(create_app(path, operator_enabled=True)) as client:
        initial = client.get("/sim/snapshot").json()
        before = light(initial)
        response = client.post(
            "/operator/mutate",
            json={"target": "sim_light_01", "values": {"power": True}, "provenance": "user"},
        )
        response.raise_for_status()
        changed = client.get("/sim/snapshot").json()
        after = light(changed)
        assert after["values"]["power"] is True
        assert after["revisions"]["power"] != before["revisions"]["power"]
        assert after["provenance"] == "user"
        assert changed["world_revision"] > initial["world_revision"]
        journal = client.get(
            "/sim/journal", params={"after": initial["world_revision"]}
        ).json()
        assert journal == sorted(journal, key=lambda row: row["sequence"])
        assert journal[-1]["before"] == before and journal[-1]["after"] == after

    with TestClient(create_app(path, operator_enabled=True)) as restarted:
        assert restarted.get("/sim/snapshot").json() == changed
        assert restarted.get(
            "/sim/journal", params={"after": initial["world_revision"]}
        ).json() == journal


def test_sim_at10_viewer_is_read_only_and_operator_is_explicit(tmp_path):
    with TestClient(create_app(tmp_path / "world.db", operator_enabled=False)) as client:
        revision = client.get("/sim/snapshot").json()["world_revision"]
        viewer = client.get("/sim/viewer")
        assert viewer.status_code == 200
        assert "fetch('/sim/snapshot')" in viewer.text and "<button" not in viewer.text
        for path in ("/sim/snapshot", "/sim/journal", "/sim/viewer"):
            assert client.post(path, json={}).status_code == 405
        assert client.post(
            "/operator/mutate", json={"target": "sim_light_01", "values": {"power": True}}
        ).status_code == 404
        assert client.get("/sim/snapshot").json()["world_revision"] == revision


def test_sim_at13_future_schema_refuses_without_writes(tmp_path):
    path = tmp_path / "future.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute("INSERT INTO schema_meta VALUES('schema_version','999')")
    db.commit()
    before = list(db.iterdump())
    db.close()
    with pytest.raises(UnsupportedSchema):
        WorldStorage(path)
    after = sqlite3.connect(path)
    assert list(after.iterdump()) == before
    after.close()


def test_sim_at14_15_invalid_sibling_is_atomic_and_journal_is_bounded(tmp_path):
    path = tmp_path / "world.db"
    with TestClient(create_app(path, operator_enabled=True)) as client:
        before = client.get("/sim/snapshot").json()
        failed = client.post(
            "/operator/mutate",
            json={
                "target": "sim_light_01",
                "values": {"power": True, "unknown": True},
                "provenance": "user",
            },
        )
        assert failed.status_code == 400
        assert client.get("/sim/snapshot").json() == before
        assert client.get("/sim/journal", params={"limit": 1}).status_code == 200
        assert client.get("/sim/journal", params={"limit": 1001}).status_code == 422
