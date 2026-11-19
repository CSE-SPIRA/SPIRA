"""Engines and sessions (spec §2.4, §3.1). Server DB read/write; KB DB read-only."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..settings import get_settings
from .models import Household


def sqlalchemy_url(url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str, *, read_only: bool = False) -> Engine:
    engine = create_engine(sqlalchemy_url(url), pool_pre_ping=True, future=True)
    if read_only:
        @event.listens_for(engine, "connect")
        def _read_only(dbapi_conn, _record):  # pragma: no cover - trivial
            with dbapi_conn.cursor() as cur:
                cur.execute("SET default_transaction_read_only = on")
            dbapi_conn.commit()
    return engine


@lru_cache(maxsize=1)
def server_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache(maxsize=1)
def kb_engine() -> Engine:
    """KB DB (read-only account). Only used when KB_MODE=on."""
    return make_engine(get_settings().kb_database_url, read_only=True)


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=server_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """One transaction: commit on success, roll back on error (spec §2.4 'one transaction per input')."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engines() -> None:
    """Drop cached engines (tests change DATABASE_URL)."""
    for cached in (server_engine, kb_engine, _session_factory):
        try:
            if cached is not _session_factory:
                cached().dispose()
        except Exception:
            pass
        cached.cache_clear()


def lock_household(session: Session, household_id: str, *, shared: bool = False) -> Household | None:
    """Household lock first, then episode rows in id order (spec §2.4). `shared` (FOR SHARE) is for readers that
    must not see a write half done, such as the card poll (§12.2)."""
    return session.execute(
        select(Household).where(Household.id == household_id).with_for_update(read=shared)
    ).scalar_one_or_none()


def next_id(session: Session, prefix: str, sequence: str) -> str:
    n = session.execute(text(f"SELECT nextval('{sequence}')")).scalar_one()
    return f"{prefix}_{n}"


def db_ready() -> bool:
    try:
        with server_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
