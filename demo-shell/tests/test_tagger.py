import asyncio
import json
from pathlib import Path

from spira_contracts.rationale import Rationale

from tagger import CHOICES, Source, TagCache, request_data, source_texts, tag_texts, validate_tags

ROOT = Path(__file__).resolve().parents[2]


def test_fixture_sources_use_only_the_allowed_rationale_texts():
    rationale = Rationale.model_validate_json((ROOT / "contracts/fixtures/ep_9031/rationale.json").read_bytes())
    sources = {f"x{i}": source for i, source in enumerate(source_texts(rationale), 1)}
    schema, prompt = request_data(sources)
    rows = json.loads(prompt.split("Source rows: ", 1)[1])
    assert "untrusted JSON data" in prompt
    assert len(rows) == 15
    assert {row["kind"] for row in rows} == {"slot", "intent", "need", "line", "notice"}
    assert all("devices" not in row for row in rows if row["kind"] != "line")
    assert next(row["devices"] for row in rows if row["text"] == rationale.tasks[1].line) == [
        "cooktop_01", "plug_kettle",
    ]
    assert [row["display_devices"] for row in rows if "display_devices" in row] == [["display_01"]]
    assert not any(item.why in prompt for item in rationale.evidence.unusual_items.items)
    assert not any(key in rows[0] for key in ("item", "basis", "ref"))
    assert schema["additionalProperties"] is False
    motifs = schema["properties"]["tags"]["items"]["properties"]["motif"]["anyOf"][0]["properties"]
    assert list(motifs) == ["center", "side", "ambient"]
    assert all(slot["enum"] == [*CHOICES["motif"], None] for slot in motifs.values())
    slots = json.loads((ROOT / "simulator/spira_simulator/ui/house/slots.json").read_bytes())
    assert "guests_enter" not in CHOICES["motion"]
    assert CHOICES["motion"] == [
        slot["id"] for slot in slots if slot["kind"] == "motion" and slot["id"] != "guests_enter"
    ]


def test_invalid_fields_do_not_discard_valid_fields():
    sources = {
        "x1": Source("line", "a", "아이 안전 모드", devices=("cooktop_01", "plug_kettle")),
        "x2": Source("notice", "b", "딸기 냉장 보관"),
        "x3": Source("line", "c", "거실 청소", devices=("cleaner_01",)),
    }
    tags, dropped = validate_tags(sources, {"tags": [
        {"id": "x1", "short": "안전 잠금", "highlights": ["안전"], "icon": "made_up",
         "devices": ["cooktop_01", "display_01"], "action": "safety_lock"},
        {"id": "x2", "short": "냉장 보관", "highlights": ["딸기", "미확인"], "icon": "strawberry",
         "storage": "cold", "devices": []},
        {"id": "x3", "short": "거실 청소", "devices": ["cleaner_01"], "motion": "cleaner_sweep"},
    ]})
    assert tags == {
        "x1": {"highlights": ["안전"], "action": "safety_lock"},
        "x2": {"short": "냉장 보관", "icon": "strawberry"},
        "x3": {"short": "거실 청소", "devices": ["cleaner_01"], "motion": "cleaner_sweep"},
    }
    assert dropped == {"short": 1, "icon": 1, "devices": 1, "highlights": 1, "storage": 1}


def test_disk_cache_reuses_text_and_checks_devices_for_each_line(tmp_path):
    requests = []

    async def request(schema, prompt):
        requests.append(prompt)
        return {"tags": [{"id": "x1", "short": "안전 모드", "action": "safety_lock", "devices": ["cooktop_01"]}]}

    def unexpected_cache(_):
        pass

    async def exercise():
        source = Source("line", "task-a", "아이 안전 모드", devices=("cooktop_01",))
        first = await tag_texts([source], TagCache(tmp_path), request, unexpected_cache)
        same = Source("line", "task-b", source.text, devices=("cooktop_01", "plug_kettle"))
        changed = Source("line", "task-c", source.text, devices=("plug_kettle",))
        second = await tag_texts([same, changed], TagCache(tmp_path), request, unexpected_cache)
        assert second == [
            {**first[0], "ref": "task-b"},
            {**first[0], "ref": "task-c", "tag": {"short": "안전 모드", "action": "safety_lock"}},
        ]

    asyncio.run(exercise())
    assert len(requests) == 1
    assert (tmp_path / "tags.sqlite3").is_file()


def test_only_display_lines_get_artwork_values_and_invalid_slots_drop_independently():
    display = Source("line", "task-a", "파티 화면과 조명", devices=("display_01", "light_01"),
                     display_devices=("display_01",))
    light = Source("line", "task-b", display.text, devices=("light_01",))
    theme = Source("slot", "theme", display.text, theme=True)
    sources = {"a": display, "b": light, "c": theme}
    response = {"palette": "princess_pink", "motif": {"center": "castle", "side": "unlisted", "ambient": "stars"}}
    tags, dropped = validate_tags(sources, {"tags": [{"id": key, **response} for key in sources]})
    assert tags == {
        "a": {"palette": "princess_pink", "motif": {"center": "castle", "ambient": "stars"}},
        "b": {},
        "c": {"palette": "princess_pink"},
    }
    assert dropped == {"motif": 3, "palette": 1}
    assert display.cache_key() != light.cache_key()
