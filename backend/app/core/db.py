"""Persistence layer: raw sqlite3 with versioned migrations and a small
repository API. No ORM on purpose -- every query is visible and indexed.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "creditsage.db"

MIGRATIONS: list[str] = [
    # 1 -- initial schema
    """
    CREATE TABLE user_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id TEXT NOT NULL,
        nickname TEXT,
        last4 TEXT,
        points_balance REAL NOT NULL DEFAULT 0,
        points_expiry TEXT,
        credit_limit REAL,
        statement_day INTEGER,
        added_at TEXT NOT NULL
    );
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_card_id INTEGER REFERENCES user_cards(id) ON DELETE SET NULL,
        amount REAL NOT NULL CHECK (amount > 0),
        merchant TEXT,
        description TEXT,
        category TEXT NOT NULL,
        category_confidence REAL,
        txn_date TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'manual',
        is_refund INTEGER NOT NULL DEFAULT 0,
        anomaly_score REAL,
        is_anomaly INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX ix_txn_date ON transactions(txn_date);
    CREATE INDEX ix_txn_card_date ON transactions(user_card_id, txn_date);
    CREATE TABLE category_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        category TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        partner TEXT NOT NULL,
        target_points REAL NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        payload TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = str(path or os.environ.get("CREDITSAGE_DB") or DEFAULT_DB)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self.migrate()

    # -- plumbing -----------------------------------------------------------
    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def migrate(self) -> int:
        with self.tx() as c:
            version = c.execute("PRAGMA user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                c.executescript(sql)
                c.execute(f"PRAGMA user_version = {i}")
            return c.execute("PRAGMA user_version").fetchone()[0]

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.tx() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    def reset(self) -> None:
        with self.tx() as c:
            for t in ("transactions", "user_cards", "category_feedback", "goals", "chat_messages", "settings"):
                c.execute(f"DELETE FROM {t}")
            c.execute("DELETE FROM sqlite_sequence")

    # -- wallet -------------------------------------------------------------
    def list_user_cards(self) -> list[dict]:
        return self.query("SELECT * FROM user_cards ORDER BY id")

    def get_user_card(self, uc_id: int) -> dict | None:
        return self.one("SELECT * FROM user_cards WHERE id = ?", (uc_id,))

    def add_user_card(self, card_id: str, nickname: str | None = None, last4: str | None = None,
                      points_balance: float = 0, points_expiry: str | None = None,
                      credit_limit: float | None = None, statement_day: int | None = None) -> int:
        return self.execute(
            "INSERT INTO user_cards (card_id, nickname, last4, points_balance, points_expiry, credit_limit, statement_day, added_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (card_id, nickname, last4, points_balance, points_expiry, credit_limit, statement_day, now_iso()))

    def update_user_card(self, uc_id: int, **fields) -> None:
        allowed = {"nickname", "last4", "points_balance", "points_expiry", "credit_limit", "statement_day"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k} = :{k}" for k in sets)
        self.execute(f"UPDATE user_cards SET {cols} WHERE id = :id", {**sets, "id": uc_id})

    def delete_user_card(self, uc_id: int) -> None:
        self.execute("DELETE FROM user_cards WHERE id = ?", (uc_id,))

    # -- transactions -------------------------------------------------------
    def add_transaction(self, **t) -> int:
        cols = ["user_card_id", "amount", "merchant", "description", "category", "category_confidence",
                "txn_date", "source", "is_refund", "anomaly_score", "is_anomaly"]
        row = {c: t.get(c) for c in cols}
        row["source"] = row["source"] or "manual"
        row["is_refund"] = int(bool(row["is_refund"]))
        row["is_anomaly"] = int(bool(row["is_anomaly"]))
        row["created_at"] = now_iso()
        names = ", ".join(row)
        ph = ", ".join(f":{k}" for k in row)
        return self.execute(f"INSERT INTO transactions ({names}) VALUES ({ph})", row)

    def list_transactions(self, start: str | None = None, end: str | None = None,
                          user_card_id: int | None = None, limit: int | None = None) -> list[dict]:
        where, params = ["1=1"], []
        if start:
            where.append("txn_date >= ?"); params.append(start)
        if end:
            where.append("txn_date < ?"); params.append(end)
        if user_card_id is not None:
            where.append("user_card_id = ?"); params.append(user_card_id)
        sql = f"SELECT * FROM transactions WHERE {' AND '.join(where)} ORDER BY txn_date DESC, id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.query(sql, tuple(params))

    def get_transaction(self, tid: int) -> dict | None:
        return self.one("SELECT * FROM transactions WHERE id = ?", (tid,))

    def update_transaction(self, tid: int, **fields) -> None:
        allowed = {"category", "category_confidence", "user_card_id", "merchant", "amount", "anomaly_score", "is_anomaly", "txn_date"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            cols = ", ".join(f"{k} = :{k}" for k in sets)
            self.execute(f"UPDATE transactions SET {cols} WHERE id = :id", {**sets, "id": tid})

    def delete_transaction(self, tid: int) -> None:
        self.execute("DELETE FROM transactions WHERE id = ?", (tid,))

    # -- feedback / goals / chat / settings ---------------------------------
    def add_feedback(self, text: str, category: str) -> None:
        self.execute("INSERT INTO category_feedback (text, category, created_at) VALUES (?,?,?)", (text, category, now_iso()))

    def list_feedback(self) -> list[dict]:
        return self.query("SELECT text, category FROM category_feedback ORDER BY id")

    def add_goal(self, name: str, partner: str, target_points: float) -> int:
        return self.execute("INSERT INTO goals (name, partner, target_points, created_at) VALUES (?,?,?,?)",
                            (name, partner, target_points, now_iso()))

    def list_goals(self) -> list[dict]:
        return self.query("SELECT * FROM goals ORDER BY id")

    def delete_goal(self, gid: int) -> None:
        self.execute("DELETE FROM goals WHERE id = ?", (gid,))

    def add_chat(self, role: str, content: str, payload: dict | None = None) -> None:
        self.execute("INSERT INTO chat_messages (role, content, payload, created_at) VALUES (?,?,?,?)",
                     (role, content, json.dumps(payload) if payload else None, now_iso()))

    def list_chat(self, limit: int = 100) -> list[dict]:
        rows = self.query("SELECT * FROM (SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?) ORDER BY id", (limit,))
        for r in rows:
            r["payload"] = json.loads(r["payload"]) if r["payload"] else None
        return rows

    def clear_chat(self) -> None:
        self.execute("DELETE FROM chat_messages")

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        r = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return r["value"] if r else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (key, value))
