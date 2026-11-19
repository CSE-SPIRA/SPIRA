"""Single-writer durable state. Transactions never span external I/O."""

import json
import sqlite3
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Store:
    def __init__(self, path: Path, household: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS plan_versions (
                plan TEXT, version INTEGER, body TEXT NOT NULL, PRIMARY KEY (plan, version)
            );
            CREATE TABLE IF NOT EXISTS tasks (
                plan TEXT, task TEXT, body TEXT NOT NULL, PRIMARY KEY (plan, task)
            );
            CREATE TABLE IF NOT EXISTS attempts (
                operation TEXT PRIMARY KEY, plan TEXT, task TEXT, action TEXT,
                target TEXT, body TEXT NOT NULL, UNIQUE (plan, task, action)
            );
            CREATE INDEX IF NOT EXISTS attempts_target ON attempts (target);
            CREATE TABLE IF NOT EXISTS signals (id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS facts (
                seq INTEGER PRIMARY KEY, target TEXT, at REAL, body TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS facts_at ON facts (at, seq);
            CREATE TABLE IF NOT EXISTS outbox (
                seq INTEGER PRIMARY KEY, id TEXT UNIQUE, kind TEXT, path TEXT, at REAL,
                packet BLOB, delivered INTEGER NOT NULL DEFAULT 0, error TEXT
            );
        """)
        if self.get("household", household) != household:
            self.db.close()
            raise ValueError("Hub database belongs to a different household")
        with self.db:
            self.put("household", household)

    def get(self, key, default=None):
        row = self.db.execute("SELECT body FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["body"]) if row else default

    def put(self, key, body):
        self.db.execute("REPLACE INTO settings VALUES (?, ?)", (key, encode(body)))

    def tasks(self, plan=None):
        where = "" if plan is None else " WHERE plan = ?"
        args = () if plan is None else (plan,)
        rows = self.db.execute("SELECT body FROM tasks" + where, args)
        return [json.loads(row["body"]) for row in rows]

    def task(self, plan, task):
        row = self.db.execute(
            "SELECT body FROM tasks WHERE plan = ? AND task = ?", (plan, task)
        ).fetchone()
        return json.loads(row["body"]) if row else None

    def save_task(self, task):
        self.db.execute(
            """
            INSERT INTO tasks VALUES (?, ?, ?)
            ON CONFLICT (plan, task) DO UPDATE SET body = excluded.body
            """,
            (task["plan"], task["id"], encode(task)),
        )

    def floor(self, plan):
        row = self.db.execute("SELECT version FROM plans WHERE id = ?", (plan,)).fetchone()
        return row["version"] if row else 0

    def advance(self, plan, version):
        self.db.execute("REPLACE INTO plans VALUES (?, ?)", (plan, version))

    def save_plan_version(self, plan, version, body):
        self.db.execute("INSERT INTO plan_versions VALUES (?, ?, ?)", (plan, version, encode(body)))

    def plan_versions(self):
        rows = self.db.execute("SELECT plan, version, body FROM plan_versions")
        return {(row["plan"], row["version"]): json.loads(row["body"]) for row in rows}

    def attempts(self, *, task=None, target=None):
        if task is not None:
            where, args = " WHERE plan = ? AND task = ?", (task["plan"], task["id"])
        elif target is not None:
            where, args = " WHERE target = ?", (target,)
        else:
            where, args = "", ()
        rows = self.db.execute("SELECT body FROM attempts" + where, args)
        return [json.loads(row["body"]) for row in rows]

    def operation(self, operation_id):
        row = self.db.execute(
            "SELECT body FROM attempts WHERE operation = ?", (operation_id,)
        ).fetchone()
        return json.loads(row["body"]) if row else None

    def reserve(self, attempt):
        self.db.execute(
            "INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?)",
            (attempt["op"], attempt["plan"], attempt["task"], attempt["action_key"],
             attempt["target"], encode(attempt)),
        )

    def save_attempt(self, attempt):
        self.db.execute(
            "UPDATE attempts SET body = ? WHERE operation = ?", (encode(attempt), attempt["op"])
        )

    def signal_is_new(self, signal):
        return bool(self.db.execute(
            "INSERT OR IGNORE INTO signals VALUES (?)", (signal,)
        ).rowcount)

    def fact(self, target, at, body):
        return self.db.execute(
            "INSERT INTO facts (target, at, body) VALUES (?, ?, ?)", (target, at, encode(body))
        ).lastrowid

    def frontier(self):
        return self.db.execute("SELECT COALESCE(MAX(seq), 0) FROM facts").fetchone()[0]

    def facts(self, *, after=0, earliest=0):
        return self.db.execute(
            "SELECT seq, target, at, body FROM facts WHERE seq > ? AND at >= ? ORDER BY at, seq",
            (after, earliest),
        ).fetchall()

    def queue(self, identity, kind, path, at, packet):
        self.db.execute(
            "INSERT INTO outbox (id, kind, path, at, packet) VALUES (?, ?, ?, ?, ?)",
            (identity, kind, path, at, packet),
        )

    def pending(self, kind):
        return self.db.execute(
            "SELECT * FROM outbox WHERE kind = ? AND delivered = 0 ORDER BY at, seq LIMIT 100",
            (kind,),
        ).fetchall()

    def delivery(self, packet, delivered, error=None):
        with self.db:
            self.db.execute(
                "UPDATE outbox SET delivered = ?, error = ? WHERE id = ?",
                (delivered, error, packet["id"]),
            )

    def evidence(self, kind, limit=100):
        return self.db.execute(
            "SELECT * FROM outbox WHERE kind = ? ORDER BY seq DESC LIMIT ?", (kind, limit)
        ).fetchall()
