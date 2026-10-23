"""Persistence for operational app state — chat conversations and use-case runs.

The KNOWLEDGE base (graph, pages, embeddings) stays in files + ArcadeDB; this module is
only for the records a product accumulates: conversations to show later, and an audit
trail of every use-case run. SQLite keeps the PoC zero-ops (one file, no container); the
same SQL maps onto Postgres later for multi-user / org deployment — swap the connection.

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
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("EAWIKI_APP_DB", "data/app.db"))


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")       # safe concurrent reads during a write
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS chats(
            id TEXT PRIMARY KEY, title TEXT, messages_json TEXT,
            created_at REAL, updated_at REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS runs(
            id TEXT PRIMARY KEY, use_case_id TEXT, submitter TEXT,
            input_json TEXT, result_json TEXT, status TEXT, created_at REAL)""")
        c.execute("CREATE INDEX IF NOT EXISTS runs_uc ON runs(use_case_id, created_at)")


def _now() -> float:
    return time.time()


# --- chats ---------------------------------------------------------------
def save_chat(messages: list, chat_id: Optional[str] = None, title: Optional[str] = None) -> dict:
    """Upsert a conversation. A new id is minted when none is given; the title defaults to
    the first user message. Returns the stored row's id + timestamps."""
    init_db()
    if not title:
        first = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        title = (first[:70] + "…") if len(first) > 70 else (first or "Untitled chat")
    now = _now()
    with _conn() as c:
        if chat_id:
            row = c.execute("SELECT created_at FROM chats WHERE id=?", (chat_id,)).fetchone()
        else:
            row = None
        if row:
            c.execute("UPDATE chats SET title=?, messages_json=?, updated_at=? WHERE id=?",
                      (title, json.dumps(messages, ensure_ascii=False), now, chat_id))
            created = row["created_at"]
        else:
            chat_id = chat_id or uuid.uuid4().hex[:12]
            created = now
            c.execute("INSERT INTO chats(id,title,messages_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                      (chat_id, title, json.dumps(messages, ensure_ascii=False), created, now))
    return {"id": chat_id, "title": title, "created_at": created, "updated_at": now}


def list_chats(limit: int = 100) -> list[dict]:
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT id,title,messages_json,created_at,updated_at FROM chats "
            "ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [{"id": r["id"], "title": r["title"], "created_at": r["created_at"],
             "updated_at": r["updated_at"],
             "n": len(json.loads(r["messages_json"] or "[]"))} for r in rows]


def get_chat(chat_id: str) -> Optional[dict]:
    init_db()
    with _conn() as c:
        r = c.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "title": r["title"], "messages": json.loads(r["messages_json"] or "[]"),
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def delete_chat(chat_id: str) -> bool:
    init_db()
    with _conn() as c:
        cur = c.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    return cur.rowcount > 0


# --- runs ----------------------------------------------------------------
def save_run(use_case_id: str, input_data, result, status: str = "done",
             submitter: Optional[str] = None) -> dict:
    """Record one use-case run (any use case — keyed by use_case_id)."""
    init_db()
    rid = uuid.uuid4().hex[:12]
    now = _now()
    with _conn() as c:
        c.execute("INSERT INTO runs(id,use_case_id,submitter,input_json,result_json,status,created_at) "
                  "VALUES(?,?,?,?,?,?,?)",
                  (rid, use_case_id, submitter, json.dumps(input_data, ensure_ascii=False),
                   json.dumps(result, ensure_ascii=False), status, now))
    return {"id": rid, "created_at": now}


def list_runs(use_case_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    init_db()
    with _conn() as c:
        if use_case_id:
            rows = c.execute("SELECT id,use_case_id,submitter,input_json,status,created_at FROM runs "
                             "WHERE use_case_id=? ORDER BY created_at DESC LIMIT ?",
                             (use_case_id, limit)).fetchall()
        else:
            rows = c.execute("SELECT id,use_case_id,submitter,input_json,status,created_at FROM runs "
                             "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        inp = json.loads(r["input_json"] or "[]")
        out.append({"id": r["id"], "use_case_id": r["use_case_id"], "submitter": r["submitter"],
                    "status": r["status"], "created_at": r["created_at"],
                    "n_items": len(inp) if isinstance(inp, list) else 1})
    return out


def get_run(run_id: str) -> Optional[dict]:
    init_db()
    with _conn() as c:
        r = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "use_case_id": r["use_case_id"], "submitter": r["submitter"],
            "input": json.loads(r["input_json"] or "null"),
            "result": json.loads(r["result_json"] or "null"),
            "status": r["status"], "created_at": r["created_at"]}
