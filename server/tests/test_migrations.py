"""Migration 0002: every §5.1 table exists in the server DB with the ORM's columns; `-x db=kb` creates only cases."""

from sqlalchemy import create_engine, inspect

from spira_server.db.engine import server_engine, sqlalchemy_url
from spira_server.db.models import Base

from .conftest import TEST_KB_DB

SPEC_TABLES = {
    "households", "device_lists", "calendar_events", "calendar_revisions", "episode_sources", "episodes",
    "episode_images", "orders", "order_items", "tasks", "plans", "cards", "card_lines", "events", "executions",
    "windows", "care_notices_shown", "llm_calls", "cases",
}


def test_server_tables_match_models():
    insp = inspect(server_engine())
    assert SPEC_TABLES <= set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        db_cols = {c["name"] for c in insp.get_columns(table.name)}
        assert {c.name for c in table.columns} <= db_cols, table.name


def test_kb_target_has_cases_only():
    engine = create_engine(sqlalchemy_url(TEST_KB_DB))
    try:
        names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert names == {"cases", "alembic_version"}
