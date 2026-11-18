"""Atomic state and journal storage for the independent World."""

from __future__ import annotations

import json
import secrets
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any


SCHEMA_VERSION = 1


class UnsupportedSchema(RuntimeError):
    pass


class InvalidMutation(ValueError):
    pass


class WorldStorage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = RLock()
        existing = self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
        ).fetchone()
        if existing:
            row = self.db.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            if not row or row[0] != str(SCHEMA_VERSION):
                self.db.close()
                raise UnsupportedSchema("unsupported Simulator schema version")

        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta(
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_meta VALUES('schema_version','1');
                CREATE TABLE IF NOT EXISTS control(
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO control VALUES('world_revision','0');
                CREATE TABLE IF NOT EXISTS device_state(
                  target TEXT PRIMARY KEY,
                  body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS world_journal(
                  sequence INTEGER PRIMARY KEY,
                  body TEXT NOT NULL
                );
                """
            )
            if not self.db.execute("SELECT 1 FROM device_state LIMIT 1").fetchone():
                light = {
                    "target": "sim_light_01",
                    "type": "light",
                    "room": "living",
                    "available": True,
                    "values": {"power": False},
                    "revisions": {"power": self._witness()},
                    "provenance": "scenario",
                    "observed_at": 0.0,
                    "substrate": "virtual",
                }
                self.db.execute(
                    "INSERT INTO device_state VALUES(?,?)",
                    (light["target"], self._encode(light)),
                )
                self._append("world.initialized", 0.0, target=light["target"], after=light)
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.db.close()
            raise

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _witness() -> str:
        return secrets.token_hex(16)

    @property
    def revision(self) -> int:
        return int(self.db.execute(
            "SELECT value FROM control WHERE key='world_revision'"
        ).fetchone()[0])

    def close(self) -> None:
        self.db.close()

    def _append(self, kind: str, at: float, **data: Any) -> int:
        revision = self.revision + 1
        self.db.execute(
            "UPDATE control SET value=? WHERE key='world_revision'", (str(revision),)
        )
        self.db.execute(
            "INSERT INTO world_journal VALUES(?,?)",
            (revision, self._encode({"kind": kind, "at": at, **data})),
        )
        return revision

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            devices = [
                json.loads(row[0])
                for row in self.db.execute("SELECT body FROM device_state ORDER BY target")
            ]
            return {
                "schema_version": SCHEMA_VERSION,
                "world_revision": self.revision,
                "substrate": "virtual",
                "viewer_writes": False,
                "devices": devices,
            }

    def journal(self, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        if after < 0 or not 1 <= limit <= 1000:
            raise InvalidMutation("journal bounds")
        with self.lock:
            return [
                {"sequence": row["sequence"], **json.loads(row["body"])}
                for row in self.db.execute(
                    "SELECT sequence,body FROM world_journal "
                    "WHERE sequence>? ORDER BY sequence LIMIT ?", (after, limit)
                )
            ]

    def mutate(
        self,
        target: str,
        values: dict[str, Any],
        provenance: str,
        at: float,
    ) -> dict[str, Any]:
        if provenance not in {"user", "scenario", "unknown"}:
            raise InvalidMutation("invalid provenance")
        with self.lock:
            row = self.db.execute(
                "SELECT body FROM device_state WHERE target=?", (target,)
            ).fetchone()
            if row is None:
                raise InvalidMutation("unknown target")
            before = json.loads(row["body"])
            unknown = sorted(set(values) - set(before["values"]))
            if unknown:
                raise InvalidMutation("unknown properties: " + ", ".join(unknown))
            if any(not isinstance(value, bool) for value in values.values()):
                raise InvalidMutation("light properties require boolean values")

            after = json.loads(self._encode(before))
            for key, value in values.items():
                after["values"][key] = value
                after["revisions"][key] = self._witness()
            after["provenance"] = provenance
            after["observed_at"] = at

            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(
                    "UPDATE device_state SET body=? WHERE target=?",
                    (self._encode(after), target),
                )
                self._append("state.changed", at, target=target, before=before, after=after)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            return after
