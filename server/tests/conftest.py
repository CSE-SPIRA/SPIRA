"""Test setup (spec §17): LLM mock, EMBED_MODE=mock, Postgres with pgvector, fixed clock.

The test databases are created next to the local one (docker compose `db` service):
  TEST_DATABASE_URL     default postgresql://spira:spira@localhost:5432/spira_test     (server DB)
  TEST_KB_DATABASE_URL  default postgresql://spira:spira@localhost:5432/spira_kb_test  (KB DB, cases only)
Both are wiped at the start of the test session. Your own `spira` database is never touched.
"""

from __future__ import annotations

import os
from pathlib import Path

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://spira:spira@localhost:5432/spira_test")
TEST_KB_DB = os.environ.get("TEST_KB_DATABASE_URL", "postgresql://spira:spira@localhost:5432/spira_kb_test")

# Environment for every test; overrides values in server/.env.
os.environ.update({
    "DATABASE_URL": TEST_DB,
    "KB_DATABASE_URL": TEST_KB_DB,
    "KB_MIGRATION_URL": TEST_KB_DB,
    "KB_VERSION": "kb-v1",
    "KB_MODE": "off",
    "HOME_CONTEXT": "on",
    "KB_SAMPLE": "1.0",
    "LLM_PROVIDER": "mock",
    "LLM_MODEL": "mock",
    "LLM_API_KEY": "",
    "LLM_TIMEOUT_S": "60",
    "EMBED_MODE": "mock",
    "APP_DEMO_TOKEN": "test-app-token",
    "CALENDAR_HMAC_KEY": "test-calendar-hmac-key-0123456789abcdef",
    "DEMO_MODE": "0",
    "IMAGE_DIR": "/tmp/spira-test-images",
    "TZ": "Asia/Seoul",
})

import psycopg
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from spira_server import clock
from spira_server.config import get_config
from spira_server.db import engine as db_engine
from spira_server.kb import embedding
from spira_server.llm import client as llm_client
from spira_server.llm.mock import MockProvider, record
from spira_server.paths import SERVER_DIR
from spira_server.settings import get_settings

SKIP_TRUNCATE = {"alembic_version"}


def _recreate(url: str) -> None:
    name = url.rsplit("/", 1)[1]
    admin = url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')


def migrate(url_env: str = "DATABASE_URL", target: str = "server") -> None:
    cfg = AlembicConfig(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    if target != "server":
        cfg.cmd_opts = type("Opts", (), {"x": [f"db={target}"]})()
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def databases():
    _recreate(TEST_DB)
    _recreate(TEST_KB_DB)
    migrate()
    migrate(target="kb")
    yield


def reset_caches() -> None:
    get_settings.cache_clear()
    get_config.cache_clear()
    db_engine.reset_engines()
    llm_client.set_llm(None)


@pytest.fixture(autouse=True)
def clean(databases):
    reset_caches()
    with db_engine.server_engine().begin() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))]
        tables = [t for t in tables if t not in SKIP_TRUNCATE]
        if tables:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
        for seq in ("household_id_seq", "episode_id_seq", "card_id_seq", "window_id_seq", "card_write_seq"):
            conn.execute(text(f"ALTER SEQUENCE {seq} RESTART WITH 1"))
    embedding.warm_up()
    clock.set_now(None)
    yield
    clock.set_now(None)
    reset_caches()


@pytest.fixture
def env(monkeypatch):
    """Change environment variables for one test: env(KB_MODE="on")."""
    def set_(**values: str) -> None:
        for k, v in values.items():
            monkeypatch.setenv(k, v)
        reset_caches()
    return set_


class MockLLM:
    """A mock LLM whose recordings live in a temporary folder."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.provider = MockProvider(folder)
        self.llm = llm_client.LLM(self.provider)

    def record(self, stage: str, system: str, user: str, images=(), **kw) -> Path:
        return record(self.folder, stage, system, user, images, **kw)

    def calls(self, stage: str | None = None) -> int:
        return self.provider.calls(stage)


@pytest.fixture
def mock_llm(tmp_path) -> MockLLM:
    m = MockLLM(tmp_path / "llm_fixtures")
    llm_client.set_llm(m.llm)
    return m


@pytest.fixture
def session():
    with db_engine.session_scope() as s:
        yield s


@pytest.fixture
def app_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-app-token"}
