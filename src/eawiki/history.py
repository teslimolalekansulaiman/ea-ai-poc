"""Persistence for operational app state — chat conversations and use-case runs.

The KNOWLEDGE base (graph, pages, embeddings) stays in files + ArcadeDB; this module is
only for the records a product accumulates: conversations to show later, and an audit
trail of every use-case run.

Pluggable behind one env var, defaulting to the zero-ops PoC backend so nothing changes
until you flip the config:

    HISTORY_BACKEND=sqlite                       # (default) one file, no container
    HISTORY_BACKEND=postgres  DATABASE_URL=...   # Cloud Run: Cloud SQL (stateless app)

Cloud Run has no durable disk and runs many short-lived instances, so SQLite-on-disk
can't be shared there — Postgres is the live store for chats + runs. The SQL is written
once and portable; only the placeholder style and the timestamp column type differ.

Two tables, both generic across use cases (demand management is just one use_case_id):
  chats(id, title, messages_json, created_at, updated_at)
  runs (id, use_case_id, submitter, input_json, result_json, status, created_at)
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("EAWIKI_APP_DB", "data/app.db"))


class _Store:
    """One backend, chosen by HISTORY_BACKEND. The query methods are shared; the backend
    only differs in how it connects and in two dialect details (`ph`, `real`)."""

    def __init__(self) -> None:
        self.backend = os.environ.get("HISTORY_BACKEND", "sqlite").lower()
        if self.backend == "postgres":
            import psycopg                       # lazy: only when HISTORY_BACKEND=postgres
            from psycopg.rows import dict_row
            self._psycopg = psycopg
            self._dict_row = dict_row
            self._dsn = os.environ.get("DATABASE_URL") or os.environ.get("EAWIKI_DATABASE_URL")
            if not self._dsn:
                raise RuntimeError("HISTORY_BACKEND=postgres requires DATABASE_URL to be set.")
            self.ph, self.real = "%s", "DOUBLE PRECISION"
        elif self.backend == "sqlite":
            self.ph, self.real = "?", "REAL"
        else:
            raise RuntimeError(f"unknown HISTORY_BACKEND '{self.backend}' (expected sqlite|postgres)")
        self._init()

    # --- connection + dialect -------------------------------------------
    def _connect(self):
        if self.backend == "postgres":
            return self._psycopg.connect(self._dsn, row_factory=self._dict_row)
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")     # safe concurrent reads during a write
        return c

    @contextmanager
    def _conn(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _sql(self, s: str) -> str:
        return s if self.ph == "?" else s.replace("?", self.ph)

    def _init(self) -> None:
        with self._conn() as c:
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS chats(
                id TEXT PRIMARY KEY, title TEXT, messages_json TEXT,
                created_at {self.real}, updated_at {self.real})"""))
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS runs(
                id TEXT PRIMARY KEY, use_case_id TEXT, submitter TEXT,
                input_json TEXT, result_json TEXT, status TEXT, created_at {self.real})"""))
            c.execute(self._sql("CREATE INDEX IF NOT EXISTS runs_uc ON runs(use_case_id, created_at)"))
            # use-case settings: the current copy of each, and every copy ever saved (so a bad edit can be put back)
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS usecase_specs(
                id TEXT PRIMARY KEY, spec_json TEXT, version INTEGER, updated_at {self.real}, deleted INTEGER DEFAULT 0)"""))
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS usecase_versions(
                vid TEXT PRIMARY KEY, use_case_id TEXT, version INTEGER, spec_json TEXT, saved_at {self.real}, note TEXT)"""))
            c.execute(self._sql("CREATE INDEX IF NOT EXISTS usecase_versions_uc ON usecase_versions(use_case_id, saved_at)"))

    # --- chats ----------------------------------------------------------
    def save_chat(self, messages: list, chat_id: Optional[str] = None,
                  title: Optional[str] = None) -> dict:
        if not title:
            first = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
            title = (first[:70] + "…") if len(first) > 70 else (first or "Untitled chat")
        now = time.time()
        payload = json.dumps(messages, ensure_ascii=False)
        with self._conn() as c:
            row = c.execute(self._sql("SELECT created_at FROM chats WHERE id=?"),
                            (chat_id,)).fetchone() if chat_id else None
            if row:
                c.execute(self._sql("UPDATE chats SET title=?, messages_json=?, updated_at=? WHERE id=?"),
                          (title, payload, now, chat_id))
                created = row["created_at"]
            else:
                chat_id = chat_id or uuid.uuid4().hex[:12]
                created = now
                c.execute(self._sql("INSERT INTO chats(id,title,messages_json,created_at,updated_at) "
                                    "VALUES(?,?,?,?,?)"), (chat_id, title, payload, created, now))
        return {"id": chat_id, "title": title, "created_at": created, "updated_at": now}

    def list_chats(self, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(self._sql(
                "SELECT id,title,messages_json,created_at,updated_at FROM chats "
                "ORDER BY updated_at DESC LIMIT ?"), (limit,)).fetchall()
        return [{"id": r["id"], "title": r["title"], "created_at": r["created_at"],
                 "updated_at": r["updated_at"],
                 "n": len(json.loads(r["messages_json"] or "[]"))} for r in rows]

    def get_chat(self, chat_id: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(self._sql("SELECT * FROM chats WHERE id=?"), (chat_id,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "title": r["title"],
                "messages": json.loads(r["messages_json"] or "[]"),
                "created_at": r["created_at"], "updated_at": r["updated_at"]}

    def delete_chat(self, chat_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute(self._sql("DELETE FROM chats WHERE id=?"), (chat_id,))
        return cur.rowcount > 0

    # --- runs -----------------------------------------------------------
    def save_run(self, use_case_id: str, input_data, result, status: str = "done",
                 submitter: Optional[str] = None) -> dict:
        rid = uuid.uuid4().hex[:12]
        now = time.time()
        with self._conn() as c:
            c.execute(self._sql(
                "INSERT INTO runs(id,use_case_id,submitter,input_json,result_json,status,created_at) "
                "VALUES(?,?,?,?,?,?,?)"),
                (rid, use_case_id, submitter, json.dumps(input_data, ensure_ascii=False),
                 json.dumps(result, ensure_ascii=False), status, now))
        return {"id": rid, "created_at": now}

    def list_runs(self, use_case_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            if use_case_id:
                rows = c.execute(self._sql(
                    "SELECT id,use_case_id,submitter,input_json,status,created_at FROM runs "
                    "WHERE use_case_id=? ORDER BY created_at DESC LIMIT ?"),
                    (use_case_id, limit)).fetchall()
            else:
                rows = c.execute(self._sql(
                    "SELECT id,use_case_id,submitter,input_json,status,created_at FROM runs "
                    "ORDER BY created_at DESC LIMIT ?"), (limit,)).fetchall()
        out = []
        for r in rows:
            inp = json.loads(r["input_json"] or "[]")
            out.append({"id": r["id"], "use_case_id": r["use_case_id"], "submitter": r["submitter"],
                        "status": r["status"], "created_at": r["created_at"],
                        "n_items": len(inp) if isinstance(inp, list) else 1})
        return out

    def get_run(self, run_id: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(self._sql("SELECT * FROM runs WHERE id=?"), (run_id,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "use_case_id": r["use_case_id"], "submitter": r["submitter"],
                "input": json.loads(r["input_json"] or "null"),
                "result": json.loads(r["result_json"] or "null"),
                "status": r["status"], "created_at": r["created_at"]}

    # --- use-case settings ----------------------------------------------
    def uc_row(self, uc_id: str) -> Optional[dict]:
        """The current row of a use case, a deleted one included (a deleted row stops the file seeding it again)."""
        with self._conn() as c:
            r = c.execute(self._sql("SELECT id,spec_json,version,updated_at,deleted FROM usecase_specs WHERE id=?"), (uc_id,)).fetchone()
        return None if not r else {"id": r["id"], "spec": json.loads(r["spec_json"] or "{}"), "version": r["version"],
                                   "updated_at": r["updated_at"], "deleted": bool(r["deleted"])}

    def uc_rows(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(self._sql("SELECT id,spec_json,version,updated_at,deleted FROM usecase_specs ORDER BY id")).fetchall()
        return [{"id": r["id"], "spec": json.loads(r["spec_json"] or "{}"), "version": r["version"],
                 "updated_at": r["updated_at"], "deleted": bool(r["deleted"])} for r in rows]

    def uc_put(self, uc_id: str, spec: dict, note: str = "") -> dict:
        """Make `spec` the current copy and keep it as a version."""
        now, payload = time.time(), json.dumps(spec, ensure_ascii=False)
        version = int(spec.get("version") or 0)
        with self._conn() as c:
            cur = c.execute(self._sql("UPDATE usecase_specs SET spec_json=?, version=?, updated_at=?, deleted=0 WHERE id=?"),
                            (payload, version, now, uc_id))
            if cur.rowcount == 0:
                c.execute(self._sql("INSERT INTO usecase_specs(id,spec_json,version,updated_at,deleted) VALUES(?,?,?,?,0)"),
                          (uc_id, payload, version, now))
            vid = uuid.uuid4().hex[:12]
            c.execute(self._sql("INSERT INTO usecase_versions(vid,use_case_id,version,spec_json,saved_at,note) VALUES(?,?,?,?,?,?)"),
                      (vid, uc_id, version, payload, now, note))
        return {"vid": vid, "saved_at": now}

    def uc_delete(self, uc_id: str) -> bool:
        """Mark it deleted (its versions stay, and the file does not bring it back)."""
        now = time.time()
        with self._conn() as c:
            cur = c.execute(self._sql("UPDATE usecase_specs SET deleted=1, updated_at=? WHERE id=? AND deleted=0"), (now, uc_id))
            if cur.rowcount:
                return True
            exists = c.execute(self._sql("SELECT 1 AS x FROM usecase_specs WHERE id=?"), (uc_id,)).fetchone()
            if not exists:
                c.execute(self._sql("INSERT INTO usecase_specs(id,spec_json,version,updated_at,deleted) VALUES(?,?,?,?,1)"),
                          (uc_id, "{}", 0, now))
        return False

    def uc_versions(self, uc_id: str, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(self._sql("SELECT vid,version,saved_at,note FROM usecase_versions WHERE use_case_id=? "
                                       "ORDER BY saved_at DESC LIMIT ?"), (uc_id, limit)).fetchall()
        return [{"vid": r["vid"], "version": r["version"], "saved_at": r["saved_at"], "note": r["note"] or ""} for r in rows]

    def uc_version(self, uc_id: str, vid: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(self._sql("SELECT spec_json FROM usecase_versions WHERE use_case_id=? AND vid=?"), (uc_id, vid)).fetchone()
        return json.loads(r["spec_json"]) if r else None


@lru_cache(maxsize=1)
def _store() -> _Store:
    return _Store()


# --- module-level API (unchanged for callers) ----------------------------
def init_db() -> None:
    _store()


def save_chat(messages: list, chat_id: Optional[str] = None, title: Optional[str] = None) -> dict:
    return _store().save_chat(messages, chat_id, title)


def list_chats(limit: int = 100) -> list[dict]:
    return _store().list_chats(limit)


def get_chat(chat_id: str) -> Optional[dict]:
    return _store().get_chat(chat_id)


def delete_chat(chat_id: str) -> bool:
    return _store().delete_chat(chat_id)


def save_run(use_case_id: str, input_data, result, status: str = "done",
             submitter: Optional[str] = None) -> dict:
    return _store().save_run(use_case_id, input_data, result, status, submitter)


def list_runs(use_case_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    return _store().list_runs(use_case_id, limit)


def get_run(run_id: str) -> Optional[dict]:
    return _store().get_run(run_id)


# --- use-case settings ---------------------------------------------------
def uc_row(uc_id: str) -> Optional[dict]:
    return _store().uc_row(uc_id)


def uc_rows() -> list[dict]:
    return _store().uc_rows()


def uc_put(uc_id: str, spec: dict, note: str = "") -> dict:
    return _store().uc_put(uc_id, spec, note)


def uc_delete(uc_id: str) -> bool:
    return _store().uc_delete(uc_id)


def uc_versions(uc_id: str, limit: int = 100) -> list[dict]:
    return _store().uc_versions(uc_id, limit)


def uc_version(uc_id: str, vid: str) -> Optional[dict]:
    return _store().uc_version(uc_id, vid)
