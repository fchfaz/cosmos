"""Penyimpanan SQLite: event, persetujuan, perangkat, outbox, KV, audit, dedup."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
  source TEXT, type TEXT NOT NULL, device TEXT, payload TEXT);
CREATE INDEX IF NOT EXISTS ix_events_type_ts ON events(type, ts);
CREATE TABLE IF NOT EXISTS approvals(
  id TEXT PRIMARY KEY, ts REAL NOT NULL, skill TEXT, action TEXT, params TEXT,
  summary TEXT, status TEXT NOT NULL, decided REAL, result TEXT);
CREATE TABLE IF NOT EXISTS devices(
  name TEXT PRIMARY KEY, platform TEXT, token_hash TEXT UNIQUE NOT NULL,
  created REAL, last_seen REAL);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, text TEXT, approval_id TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor TEXT, what TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS seen(key TEXT PRIMARY KEY, ts REAL);
"""


class Database:
    def __init__(self, path: str | Path):
        path = str(path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ---- util -----------------------------------------------------------
    def _run(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self._all(sql, args)
        return rows[0] if rows else None

    # ---- events ---------------------------------------------------------
    def insert_event(self, source: str, type_: str, device: str | None, payload: dict, ts: float | None = None) -> int:
        cur = self._run(
            "INSERT INTO events(ts,source,type,device,payload) VALUES(?,?,?,?,?)",
            (ts or time.time(), source, type_, device, json.dumps(payload, ensure_ascii=False, default=str)),
        )
        return int(cur.lastrowid)

    def recent_events(self, limit: int = 20, type_: str | None = None, since: float | None = None,
                      device: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM events WHERE 1=1", []
        if type_:
            sql += " AND type=?"; args.append(type_)
        if since:
            sql += " AND ts>=?"; args.append(since)
        if device:
            sql += " AND device=?"; args.append(device)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"; args.append(limit)
        rows = self._all(sql, tuple(args))
        for r in rows:
            r["payload"] = json.loads(r["payload"] or "{}")
        return rows

    # ---- approvals ------------------------------------------------------
    def create_approval(self, skill: str, action: str, params: dict, summary: str) -> str:
        aid = uuid.uuid4().hex[:8]
        self._run(
            "INSERT INTO approvals(id,ts,skill,action,params,summary,status) VALUES(?,?,?,?,?,?,'pending')",
            (aid, time.time(), skill, action, json.dumps(params, ensure_ascii=False, default=str), summary),
        )
        return aid

    def get_approval(self, aid: str) -> dict | None:
        row = self._one("SELECT * FROM approvals WHERE id=?", (aid,))
        if row:
            row["params"] = json.loads(row["params"] or "{}")
            row["result"] = json.loads(row["result"]) if row["result"] else None
        return row

    def update_approval(self, aid: str, **fields: Any) -> None:
        if not fields:
            return
        for k in ("params", "result"):
            if k in fields:
                fields[k] = json.dumps(fields[k], ensure_ascii=False, default=str)
        cols = ",".join(f"{k}=?" for k in fields)
        self._run(f"UPDATE approvals SET {cols} WHERE id=?", (*fields.values(), aid))

    def pending_approvals(self) -> list[dict]:
        rows = self._all("SELECT * FROM approvals WHERE status='pending' ORDER BY ts")
        for r in rows:
            r["params"] = json.loads(r["params"] or "{}")
        return rows

    # ---- devices --------------------------------------------------------
    def add_device(self, name: str, platform: str, token_hash: str) -> None:
        self._run(
            "INSERT OR REPLACE INTO devices(name,platform,token_hash,created,last_seen) VALUES(?,?,?,?,NULL)",
            (name, platform, token_hash, time.time()),
        )

    def device_by_hash(self, token_hash: str) -> dict | None:
        return self._one("SELECT * FROM devices WHERE token_hash=?", (token_hash,))

    def touch_device(self, name: str) -> None:
        self._run("UPDATE devices SET last_seen=? WHERE name=?", (time.time(), name))

    def list_devices(self) -> list[dict]:
        return self._all("SELECT name,platform,created,last_seen FROM devices ORDER BY name")

    def remove_device(self, name: str) -> bool:
        return self._run("DELETE FROM devices WHERE name=?", (name,)).rowcount > 0

    # ---- outbox ---------------------------------------------------------
    def add_outbox(self, text: str, approval_id: str | None = None) -> int:
        return int(self._run("INSERT INTO outbox(ts,text,approval_id) VALUES(?,?,?)",
                             (time.time(), text, approval_id)).lastrowid)

    def outbox_after(self, after: int = 0, limit: int = 50) -> list[dict]:
        return self._all("SELECT * FROM outbox WHERE id>? ORDER BY id LIMIT ?", (after, limit))

    # ---- kv -------------------------------------------------------------
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        self._run("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)",
                  (key, json.dumps(value, ensure_ascii=False, default=str)))

    # ---- audit / dedup --------------------------------------------------
    def audit(self, actor: str, what: str, detail: Any = None) -> None:
        self._run("INSERT INTO audit(ts,actor,what,detail) VALUES(?,?,?,?)",
                  (time.time(), actor, what, json.dumps(detail, ensure_ascii=False, default=str)[:2000]))

    def recent_audit(self, limit: int = 20) -> list[dict]:
        return self._all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))

    def seen_recently(self, key: str, window_seconds: float) -> bool:
        """True bila key sudah terlihat dalam jendela waktu. Selalu menyegarkan cap waktunya."""
        now = time.time()
        row = self._one("SELECT ts FROM seen WHERE key=?", (key,))
        dup = bool(row and now - row["ts"] < window_seconds)
        self._run("INSERT OR REPLACE INTO seen(key,ts) VALUES(?,?)", (key, now))
        if len(key) and now % 50 < 1:  # pembersihan oportunistik
            self._run("DELETE FROM seen WHERE ts<?", (now - 86400,))
        return dup
