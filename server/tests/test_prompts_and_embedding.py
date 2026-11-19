"""Prompt lists are filled from contracts/kb and config; mock embedding is deterministic (spec §6.3, §3.1)."""

from spira_server.kb import embedding
from spira_server.kb.lists import get_lists
from spira_server.llm import prompts


def test_system_prompts_have_no_placeholders():
    for stage in ("s1", "retype", "cal", "s3", "s4"):
        text = prompts.system(stage)
        assert "{" not in text.replace("{n}", ""), stage


def test_lists_filled():
    assert "음·식료품 / 농축수산물" in prompts.system("s1")
    s3 = prompts.system("s3")
    assert all(f"{i.id} · {i.name} · " in s3 for i in get_lists().intents)
    assert len(get_lists().intents) == 30
    cal = prompts.system("cal")
    assert "생일 · 누군가의 생일·생일 파티 (생신, 생파 포함)" in cal
    assert len(get_lists().calendar_tags) == 30


def test_mock_embedding():
    a = embedding.embed_basket(["딸기", "풍선", "고깔모자"])
    b = embedding.embed_basket(["고깔모자", "딸기", "풍선"])
    c = embedding.embed_basket(["딸기", "풍선", "케이크 토퍼"])
    d = embedding.embed_basket(["세탁 세제"])
    assert len(a) == 1024 and abs(embedding.cosine(a, a) - 1) < 1e-9
    assert a == b
    assert embedding.cosine(a, c) > 0.6 > abs(embedding.cosine(a, d))
    assert embedding.cosine(embedding.embed_basket(["딸기"]), embedding.embed_basket(["딸기"])) > 0.999
