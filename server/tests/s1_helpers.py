"""Helpers for S1 tests: post captures, record the S1 LLM output, run the quiet timer."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from spira_server import clock, scheduler
from spira_server.llm import prompts
from spira_server.main import create_app
from spira_server.pipeline import s1_extract

THU_2100 = clock.parse("2026-10-15T21:00:08+09:00")


def client() -> TestClient:
    scheduler.clear()
    return TestClient(create_app(start_background=False))


def post(c: TestClient, headers: dict, images: list[bytes], hid: str = "h_042", source_id: str | None = None,
         shared_at: str | None = None):
    files = [("images", (f"s{i}.png", img, "image/png")) for i, img in enumerate(images)]
    form = {"household_id": hid}
    if source_id:
        form["source_id"] = source_id
    if shared_at:
        form["shared_at"] = shared_at
    return c.post("/v1/orders", data=form, files=files, headers=headers)


def user_text(n: int) -> str:
    return prompts.fill(prompts.text("s1_user.txt"), N=n) if n > 1 else prompts.text("s1_user_one.txt")


def record_s1(mock_llm, images: list[bytes], **kw):
    return mock_llm.record("s1", prompts.system("s1"), user_text(len(images)), images, **kw)


def run_quiet(episode_id: str, at: datetime) -> None:
    clock.set_now(at)
    s1_extract.on_quiet(episode_id)
