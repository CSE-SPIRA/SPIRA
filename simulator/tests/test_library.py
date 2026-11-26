import re

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from spira_simulator.api import create_app


def test_library_serves_without_operator_access_and_publishes_valid_slots(tmp_path):
    app = create_app(tmp_path / "world.db", operator_enabled=False, broker_enabled=False)
    with TestClient(app) as client:
        page = client.get("/sim/library")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert 'id="house-stage"' in page.text
        assert 'id="slot-grid"' in page.text
        assert 'data-camera="living_room"' in page.text
        assert 'data-camera="dining_table"' in page.text
        assert "거실 조명 예시 상태" in page.text
        assert 'id="sample-light-status" aria-live="polite">꺼짐' in page.text
        assert 'id="sample-light-off" type="button">조명 끄기' in page.text

        assets = "/sim/assets/house/"
        for asset in ("library.js", "library.css", "library-scene.js", "slots.js", "ceiling-cove.js", "room-wash.js"):
            assert client.get(assets + asset).status_code == 200
        response = client.get(assets + "slots.json")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

    slots = response.json()
    assert isinstance(slots, list) and slots
    slot_ids = set()
    for slot in slots:
        assert set(slot) == {"id", "kind", "label", "parameters", "anchors"}
        assert re.fullmatch(r"[a-z][a-z0-9_]*", slot["id"])
        assert slot["id"] not in slot_ids
        slot_ids.add(slot["id"])
        assert slot["kind"] in {"goods", "person", "effect", "surface", "motion"}
        assert re.search(r"[가-힣]", slot["label"])
        assert isinstance(slot["anchors"], list) and slot["anchors"]
        assert len(set(slot["anchors"])) == len(slot["anchors"])
        assert isinstance(slot["parameters"], dict)
        for rule in slot["parameters"].values():
            Draft202012Validator.check_schema(rule)
            Draft202012Validator(rule, format_checker=FormatChecker()).validate(rule["default"])
