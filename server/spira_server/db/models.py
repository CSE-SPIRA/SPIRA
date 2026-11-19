"""ORM models of the server DB (spec §5.1). The tables are created by migrations 0001 and 0002; keep both in step."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Text, func
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class Household(Base):
    __tablename__ = "households"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    household_types: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    hub_key_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class DeviceList(Base):
    __tablename__ = "device_lists"
    household_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    household_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    start: Mapped[datetime] = mapped_column(TS)
    end: Mapped[datetime] = mapped_column("end", TS)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    tagged: Mapped[bool] = mapped_column(Boolean, default=False)
    fingerprint: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class CalendarRevision(Base):
    __tablename__ = "calendar_revisions"
    household_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class Episode(Base):
    __tablename__ = "episodes"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    household_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    shared_at: Mapped[datetime] = mapped_column(TS)
    received_at: Mapped[datetime] = mapped_column(TS)
    source_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    judged: Mapped[bool] = mapped_column(Boolean, default=False)
    stage: Mapped[str | None] = mapped_column(Text)
    quiet_due: Mapped[datetime | None] = mapped_column(TS)
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    context: Mapped[dict | None] = mapped_column(JSONB)
    intent: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[dict | None] = mapped_column(JSONB)
    closed_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())
    next_item_n: Mapped[int] = mapped_column(Integer, default=1)
    next_task_n: Mapped[int] = mapped_column(Integer, default=1)
    next_card_ordinal: Mapped[int] = mapped_column(Integer, default=1)
    rerun_pending: Mapped[bool] = mapped_column(Boolean, default=False)


class EpisodeSource(Base):
    __tablename__ = "episode_sources"
    household_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    episode_id: Mapped[str] = mapped_column(Text)


class EpisodeImage(Base):
    __tablename__ = "episode_images"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    episode_id: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    episode_id: Mapped[str] = mapped_column(Text)
    order_no: Mapped[str | None] = mapped_column(Text)
    mall: Mapped[str | None] = mapped_column(Text)
    eta_text: Mapped[str | None] = mapped_column(Text)


class OrderItem(Base):
    __tablename__ = "order_items"
    episode_id: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_no: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    grp: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    qty: Mapped[int | None] = mapped_column(Integer)
    deal: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[list | None] = mapped_column(JSONB)
    masked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"
    episode_id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    card_id: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    way: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    need: Mapped[str | None] = mapped_column(Text)
    line: Mapped[str | None] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(JSONB)
    trigger: Mapped[dict | None] = mapped_column(JSONB)
    end: Mapped[dict] = mapped_column("end", JSONB)
    target_room: Mapped[str | None] = mapped_column(Text)
    end_after_start_minutes: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    ended_at: Mapped[datetime | None] = mapped_column(TS)
    drop_reason: Mapped[str | None] = mapped_column(Text)
    restore: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Plan(Base):
    __tablename__ = "plans"
    episode_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    body: Mapped[dict] = mapped_column(JSONB)
    devices_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    ack: Mapped[dict | None] = mapped_column(JSONB)
    acked_at: Mapped[datetime | None] = mapped_column(TS)


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    episode_id: Mapped[str] = mapped_column(Text)
    bundle_index: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    intent_id: Mapped[str] = mapped_column(Text)
    template: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(TS)
    stopped: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    notify: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(TS)
    seq: Mapped[int] = mapped_column(BigInteger, server_default=sql_text("nextval('card_write_seq')"))


class CardLine(Base):
    __tablename__ = "card_lines"
    card_id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    checked: Mapped[bool] = mapped_column(Boolean, default=True)
    checked_changed_at: Mapped[datetime | None] = mapped_column(TS)
    state: Mapped[str] = mapped_column(Text)
    end_state: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class Event(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    household_id: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(TS)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    received_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Execution(Base):
    __tablename__ = "executions"
    result_id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    operation_id: Mapped[str | None] = mapped_column(Text)
    plan_id: Mapped[str] = mapped_column(Text)
    plan_version: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[str] = mapped_column(Text)
    device: Mapped[str | None] = mapped_column(Text)
    cmd: Mapped[str | None] = mapped_column(Text)
    substrate: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    body: Mapped[dict] = mapped_column(JSONB)
    at: Mapped[datetime] = mapped_column(TS)
    received_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Window(Base):
    __tablename__ = "windows"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    episode_id: Mapped[str] = mapped_column(Text)
    card_id: Mapped[str] = mapped_column(Text)
    start_at: Mapped[datetime | None] = mapped_column(TS)
    scheduled_start: Mapped[datetime | None] = mapped_column(TS)
    end_due: Mapped[datetime | None] = mapped_column(TS)
    end_at: Mapped[datetime | None] = mapped_column(TS)
    end_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    memory: Mapped[str] = mapped_column(Text, default="pending")
    verdict: Mapped[str | None] = mapped_column(Text)
    task_feedback: Mapped[list | None] = mapped_column(JSONB)
    checks: Mapped[dict] = mapped_column(JSONB, default=dict)


class CareNoticeShown(Base):
    __tablename__ = "care_notices_shown"
    household_id: Mapped[str] = mapped_column(Text, primary_key=True)
    item_type: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class LlmCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    episode_id: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class Case(Base):
    """`cases` from migration 0001 (both DBs). Columns must not change."""

    __tablename__ = "cases"
    case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    items: Mapped[list[str]] = mapped_column(ARRAY(Text))
    intent_id: Mapped[str] = mapped_column(Text)
    intent_text: Mapped[str | None] = mapped_column(Text)
    situation: Mapped[dict] = mapped_column(JSONB, default=dict)
    when: Mapped[dict] = mapped_column("when", JSONB, default=dict)
    household: Mapped[dict] = mapped_column(JSONB, default=dict)
    basket_emb: Mapped[list[float]] = mapped_column(Vector(1024))
    kb_version: Mapped[str | None] = mapped_column(Text)
    household_id: Mapped[str | None] = mapped_column(Text)
    home_did: Mapped[list | None] = mapped_column(JSONB)
    verdict: Mapped[str | None] = mapped_column(Text)
    task_feedback: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
