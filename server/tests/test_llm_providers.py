"""Anthropic adapter (spec §6.1): JSON outputs via `output_config.format`, no forced tool use (dry run A, 11-21).

No network: the SDK client is replaced by a fake that records the request and returns a canned message.
The four stage schemas are checked against the documented limits of strict schemas (16 unions, 24 optional fields).
"""

import json
from types import SimpleNamespace

import pytest

from spira_server.config import get_config, load_yaml
from spira_server.kb.lists import get_lists
from spira_server.llm.client import LLMError
from spira_server.llm.providers import AnthropicProvider, anthropic_output_schema
from spira_server.paths import SERVER_DIR
from spira_server.pipeline import s1_extract, s2_calendar, s3_intent, s4_tasks

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


class FakeMessages:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.kwargs = reply, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.reply


def _message(text, stop_reason="end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason,
                           usage=SimpleNamespace(input_tokens=120, output_tokens=30))


def _provider(messages):
    p = AnthropicProvider("claude-sonnet-5-5", "test-key")
    p.client = SimpleNamespace(messages=messages)
    return p


SCHEMA = {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1}}, "required": ["n"]}


def _complete(p, images=()):
    return p.complete(stage="s1", system="시스템", user="질문", json_schema=SCHEMA, schema_name="Answer",
                      images=list(images), timeout_s=60)


def test_request_uses_json_output_not_tool_choice():
    m = FakeMessages(_message('{"n": 3}'))
    reply = _complete(_provider(m), images=[PNG])
    assert "tool_choice" not in m.kwargs and "tools" not in m.kwargs
    fmt = m.kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert "minimum" not in fmt["schema"]["properties"]["n"]
    content = m.kwargs["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "text"]
    assert content[0]["source"]["media_type"] == "image/png"
    assert (reply.data, reply.refusal, reply.input_tokens, reply.output_tokens) == ({"n": 3}, False, 120, 30)


def test_refusal_and_truncation_are_format_errors_upstream():
    refused = _complete(_provider(FakeMessages(_message("", stop_reason="refusal"))))
    assert refused.refusal and refused.data is None
    cut = _complete(_provider(FakeMessages(_message('{"n": ', stop_reason="max_tokens"))))
    assert cut.data is None and cut.text == '{"n": '


def test_api_error_is_llm_error():
    import anthropic
    import httpx

    err = anthropic.BadRequestError("bad", response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
                                    body=None)
    with pytest.raises(LLMError):
        _complete(_provider(FakeMessages(error=err)))


def _limits(schema):
    unions = optional = 0

    def walk(n):
        nonlocal unions, optional
        if isinstance(n, dict):
            if "anyOf" in n or isinstance(n.get("type"), list):
                unions += 1
            if "properties" in n:
                optional += sum(1 for k in n["properties"] if k not in set(n.get("required", [])))
                assert n.get("additionalProperties") is False
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(schema)
    return unions, optional


def test_stage_schemas_fit_json_output_limits():
    home = load_yaml((SERVER_DIR / "dev" / "home.example.yaml").read_text(encoding="utf-8"))
    devices = json.loads((SERVER_DIR / "dev" / home["devices_from"]).read_text(encoding="utf-8"))["devices"]
    catalog = s4_tasks.catalog_from({"household_id": "h_t", "revision": 1,
                                     "devices": devices + home["extra_devices"]})
    items = ["접시", "케이크 토퍼", "종이컵", "콩나물", "딸기", "우유 케이크", "휘핑크림", "두부"]
    schemas = {
        "s1": s1_extract.extraction_model(get_config().product_groups),
        "cal": s2_calendar.tagging_schema(["c1", "c2", "c3", "c4", "c5"]),
        "s3": s3_intent.build_schema(items, ["c1", "c2"], get_lists().intent_ids),
        "s4": s4_tasks.build_task_schema(catalog, 2, ["딸기", "휘핑크림", "콩나물", "두부", "우유 케이크"]),
    }
    for stage, model in schemas.items():
        unions, optional = _limits(anthropic_output_schema(model.model_json_schema()))
        assert unions <= 16 and optional <= 24, (stage, unions, optional)


def test_s4_style_call_sends_the_schema_as_text():
    m = FakeMessages(_message('설명입니다.\n```json\n{"n": 3}\n```'))
    p = _provider(m)
    reply = p.complete(stage="s4", system="시스템", user="질문", json_schema=SCHEMA, schema_name="Answer",
                       images=[], timeout_s=60, enforce_schema=False)
    assert "output_config" not in m.kwargs and "tool_choice" not in m.kwargs
    assert m.kwargs["system"].startswith("시스템\n\n[답 JSON 스키마]\n")
    assert m.kwargs["system"].endswith(json.dumps(SCHEMA, ensure_ascii=False, separators=(",", ":")))
    assert reply.data == {"n": 3}


def test_openai_without_enforced_schema_uses_json_object():
    from spira_server.llm.providers import OpenAIProvider

    class Completions:
        kwargs = None

        def create(self, **kw):
            Completions.kwargs = kw
            msg = SimpleNamespace(content='{"n": 1}', refusal=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)],
                                   usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2))

    p = OpenAIProvider("gpt-test", "test-key")
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    reply = p.complete(stage="s4", system="시스템", user="질문", json_schema=SCHEMA, schema_name="Answer",
                       images=[], timeout_s=60, enforce_schema=False)
    assert Completions.kwargs["response_format"] == {"type": "json_object"}
    assert "[답 JSON 스키마]" in Completions.kwargs["messages"][0]["content"]
    assert reply.text == '{"n": 1}'


def test_parse_json_text_unwraps_prose_and_fences():
    from spira_server.llm.client import parse_json_text

    assert parse_json_text('{"a": 1}') == {"a": 1}
    assert parse_json_text('답:\n```json\n{"a": {"b": 2}}\n```\n끝') == {"a": {"b": 2}}
    with pytest.raises(json.JSONDecodeError):
        parse_json_text("JSON 없음")


def test_only_s4_runs_without_enforced_schema(mock_llm):
    from spira_server.pipeline import s4_tasks

    from . import s4_helpers

    real = mock_llm.llm.provider
    seen = {}

    class Spy:
        name, model = real.name, real.model

        def complete(self, **kw):
            seen[kw["stage"]] = kw["enforce_schema"]
            return real.complete(**kw)

    ep = s4_helpers.ep9031()
    s4_helpers.record(mock_llm, ep, s4_helpers.output())
    mock_llm.llm.provider = Spy()
    try:
        s4_tasks.generate(ep, now=s4_helpers.JUDGED)
    finally:
        mock_llm.llm.provider = real
    assert seen == {"s4": False}
