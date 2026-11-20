"""SQLite storage for device state, durable receipts, and private truth."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = 2


class UnsupportedSchema(RuntimeError):
    pass


def identity(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def encode(value: Any) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


def sortable_time(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="microseconds")


class WorldStorage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.lock = RLock()
        try:
            self._open()
        except BaseException:
            self.db.close()
            raise

    def _open(self):
        has_meta = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        version = None
        if has_meta:
            row = self.db.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            version = row[0] if row else ""
            if version not in {"1", str(SCHEMA_VERSION)}:
                raise UnsupportedSchema("unsupported Simulator schema version")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        with self.transaction():
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS control(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS devices(target TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS truth_journal(sequence INTEGER PRIMARY KEY, body TEXT NOT NULL)"
            )
            self.db.execute(
                """CREATE TABLE IF NOT EXISTS command_truth(
                    sequence INTEGER PRIMARY KEY,
                    operation_id TEXT NOT NULL,
                    target TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    is_notice INTEGER NOT NULL
                )"""
            )
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS command_truth_time ON command_truth(occurred_at)"
            )
            self.db.execute(
                "INSERT OR IGNORE INTO control VALUES('world_revision','0')"
            )
            self.db.execute(
                "INSERT OR IGNORE INTO control VALUES('world_epoch',?)",
                (identity("we"),),
            )
            # A v1 snapshot can seed the reference light without copying its unverified provenance.
            if version == "1":
                row = self.db.execute(
                    "SELECT body FROM device_state WHERE target='sim_light_01'"
                ).fetchone()
                if row:
                    old = json.loads(row[0])
                    self.db.execute(
                        "INSERT INTO control VALUES('legacy_light',?)",
                        (
                            encode(
                                {
                                    "value": old["values"]["power"],
                                    "witness": old["revisions"]["power"],
                                    "at": old["observed_at"],
                                }
                            ),
                        ),
                    )
            self.db.execute(
                "INSERT OR REPLACE INTO schema_meta VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def close(self):
        with self.lock:
            self.db.close()

    def control(self, key: str) -> str | None:
        row = self.db.execute(
            "SELECT value FROM control WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else None

    def save_control(self, key: str, value: str):
        self.db.execute("INSERT OR REPLACE INTO control VALUES(?,?)", (key, value))

    @property
    def revision(self) -> int:
        return int(self.control("world_revision"))

    def state(self, target: str) -> dict | None:
        row = self.db.execute(
            "SELECT body FROM devices WHERE target=?", (target,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_state(self, target: str, state: dict):
        self.db.execute(
            "INSERT OR REPLACE INTO devices VALUES(?,?)", (target, encode(state))
        )

    def receipt(self, operation_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT body FROM receipts WHERE id=?", (operation_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_receipt(self, operation_id: str, receipt: dict):
        self.db.execute(
            "INSERT INTO receipts VALUES(?,?)", (operation_id, encode(receipt))
        )

    def record_command(
        self, operation_id: str, target: str, at: datetime, *, is_notice: bool
    ):
        self.db.execute(
            """INSERT INTO command_truth(operation_id, target, occurred_at, is_notice)
               VALUES(?,?,?,?)""",
            (operation_id, target, sortable_time(at), is_notice),
        )

    def mark_commands(self, at: datetime) -> dict:
        (sequence,) = self.db.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM command_truth"
        ).fetchone()
        marker = {"at": at.isoformat(), "sequence": sequence}
        self.save_control("command_marker", encode(marker))
        return marker

    def count_commands(
        self, *, after: int = 0, start: datetime | None = None, end: datetime | None = None
    ) -> dict:
        query = """
            SELECT target, SUM(is_notice), COUNT(*) - SUM(is_notice)
            FROM command_truth
        """
        if start is not None and end is not None:
            where = "WHERE occurred_at >= ? AND occurred_at < ?"
            bounds = (sortable_time(start), sortable_time(end))
        else:
            where = "WHERE sequence > ?"
            bounds = (after,)
        return {
            target: {"notices": notices, "other_commands": other_commands}
            for target, notices, other_commands in self.db.execute(
                f"{query} {where} GROUP BY target", bounds
            )
        }

    def append_truth(self, fact: dict) -> int:
        sequence = self.revision + 1
        self.db.execute(
            "UPDATE control SET value=? WHERE key='world_revision'", (str(sequence),)
        )
        self.db.execute(
            "INSERT INTO truth_journal VALUES(?,?)", (sequence, encode(fact))
        )
        return sequence

    def truth(self, after: int = 0, limit: int | None = None) -> list[dict]:
        with self.lock:
            return [
                {"sequence": sequence, **json.loads(body)}
                for sequence, body in self.db.execute(
                    "SELECT sequence, body FROM truth_journal WHERE sequence>? ORDER BY sequence LIMIT ?",
                    (after, -1 if limit is None else limit),
                )
            ]

    def latest_truth(self) -> list[dict]:
        """Latest actual value transition per device."""
        return [
            json.loads(body)
            for (body,) in self.db.execute(
                """SELECT body FROM truth_journal
                   WHERE sequence IN (
                       SELECT MAX(sequence) FROM truth_journal
                       WHERE json_extract(body, '$.logical_id') IS NOT NULL
                         AND json_extract(body, '$.event_type') NOT LIKE '%.availability'
                         AND json_extract(body, '$.before') IS NOT json_extract(body, '$.after')
                       GROUP BY json_extract(body, '$.target')
                   )
                   ORDER BY sequence"""
            )
        ]

    def home_truth(self, event_types: tuple[str, ...]) -> list[dict]:
        placeholders = ", ".join("?" for _ in event_types)
        return [
            json.loads(body)
            for (body,) in self.db.execute(
                f"""SELECT body FROM truth_journal
                    WHERE json_extract(body, '$.logical_id') IS NULL
                      AND json_extract(body, '$.event_type') IN ({placeholders})
                    ORDER BY sequence""",
                event_types,
            )
        ]
