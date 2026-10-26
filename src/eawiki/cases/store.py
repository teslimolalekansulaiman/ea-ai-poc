"""Persistence for cases: one row per case, one per cell, an event log and open questions.

Built on the same connection helper as `history` (SQLite by default, Postgres on Cloud Run), so
the portable SQL and the HISTORY_BACKEND switch are shared. A cell is saved the moment it is
decided, so the screen can show it filling in and a crash loses nothing.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from functools import lru_cache
from typing import Optional

from eawiki import history


class CaseStore(history._Store):
    def _connect(self):
        if self.backend == "sqlite":
            history.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(history.DB_PATH, timeout=30)     # many worker threads write
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            return c
        return super()._connect()

    def _init(self) -> None:
        super()._init()
        r = self.real
        with self._conn() as c:
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS cases(
                id TEXT PRIMARY KEY, use_case_id TEXT, name TEXT, spec_json TEXT, items_json TEXT,
                state_json TEXT, created_at {r}, updated_at {r})"""))
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS cells(
                case_id TEXT, item_id TEXT, phase_id TEXT, col TEXT, value_json TEXT, status TEXT,
                source TEXT, evidence_json TEXT, how_json TEXT, need TEXT, review TEXT,
                updated_at {r}, PRIMARY KEY(case_id, item_id, phase_id, col))"""))
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS case_events(
                case_id TEXT, seq INTEGER, ts {r}, kind TEXT, data_json TEXT,
                PRIMARY KEY(case_id, seq))"""))
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS questions(
                id TEXT PRIMARY KEY, case_id TEXT, item_id TEXT, phase_id TEXT, col TEXT,
                text TEXT, status TEXT, answer TEXT, created_at {r})"""))
            c.execute(self._sql("CREATE INDEX IF NOT EXISTS cases_uc ON cases(use_case_id, updated_at)"))

    # --- cases --------------------------------------------------------------
    def create_case(self, use_case_id: str, name: str, spec: dict, items: list[dict]) -> str:
        cid = uuid.uuid4().hex[:12]
        now = time.time()
        with self._conn() as c:
            c.execute(self._sql(
                "INSERT INTO cases(id,use_case_id,name,spec_json,items_json,state_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)"),
                (cid, use_case_id, name, json.dumps(spec, ensure_ascii=False),
                 json.dumps(items, ensure_ascii=False), json.dumps({"phases": {}}), now, now))
        return cid

    def get_case(self, cid: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(self._sql("SELECT * FROM cases WHERE id=?"), (cid,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "use_case_id": r["use_case_id"], "name": r["name"],
                "spec": json.loads(r["spec_json"]), "items": json.loads(r["items_json"]),
                "state": json.loads(r["state_json"] or "{}"),
                "created_at": r["created_at"], "updated_at": r["updated_at"]}

    def list_cases(self, limit: int = 100) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(self._sql(
                "SELECT id,use_case_id,name,items_json,state_json,created_at,updated_at FROM cases "
                "ORDER BY updated_at DESC LIMIT ?"), (limit,)).fetchall()
        return [{"id": r["id"], "use_case_id": r["use_case_id"], "name": r["name"],
                 "n_items": len(json.loads(r["items_json"] or "[]")),
                 "state": json.loads(r["state_json"] or "{}"),
                 "created_at": r["created_at"], "updated_at": r["updated_at"]} for r in rows]

    def set_phase(self, cid: str, phase_id: str, **fields) -> dict:
        """Merge fields into one phase's state (status, counts, started/finished)."""
        with self._conn() as c:
            r = c.execute(self._sql("SELECT state_json FROM cases WHERE id=?"), (cid,)).fetchone()
            st = json.loads((r["state_json"] if r else None) or "{}")
            ph = st.setdefault("phases", {}).setdefault(phase_id, {})
            ph.update(fields)
            c.execute(self._sql("UPDATE cases SET state_json=?, updated_at=? WHERE id=?"),
                      (json.dumps(st), time.time(), cid))
        return ph

    def delete_case(self, cid: str) -> bool:
        with self._conn() as c:
            for t in ("cells", "case_events", "questions"):
                c.execute(self._sql(f"DELETE FROM {t} WHERE case_id=?"), (cid,))
            cur = c.execute(self._sql("DELETE FROM cases WHERE id=?"), (cid,))
        return cur.rowcount > 0

    # --- cells --------------------------------------------------------------
    def save_cell(self, cid: str, item_id: str, phase_id: str, col: str, *, value, status: str,
                  source: str = "model", evidence=None, how=None, need: str = "",
                  review: str = "") -> None:
        now = time.time()
        with self._conn() as c:
            c.execute(self._sql(
                "INSERT INTO cells(case_id,item_id,phase_id,col,value_json,status,source,evidence_json,"
                "how_json,need,review,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(case_id,item_id,phase_id,col) DO UPDATE SET value_json=excluded.value_json,"
                "status=excluded.status,source=excluded.source,evidence_json=excluded.evidence_json,"
                "how_json=excluded.how_json,need=excluded.need,review=excluded.review,"
                "updated_at=excluded.updated_at"),
                (cid, item_id, phase_id, col, json.dumps(value, ensure_ascii=False), status, source,
                 json.dumps(evidence or [], ensure_ascii=False), json.dumps(how or [], ensure_ascii=False),
                 need or "", review or "", now))

    def cells(self, cid: str, phase_id: Optional[str] = None) -> list[dict]:
        with self._conn() as c:
            if phase_id:
                rows = c.execute(self._sql("SELECT * FROM cells WHERE case_id=? AND phase_id=?"),
                                 (cid, phase_id)).fetchall()
            else:
                rows = c.execute(self._sql("SELECT * FROM cells WHERE case_id=?"), (cid,)).fetchall()
        return [{"item_id": r["item_id"], "phase_id": r["phase_id"], "column": r["col"],
                 "value": json.loads(r["value_json"]), "status": r["status"], "source": r["source"],
                 "evidence": json.loads(r["evidence_json"] or "[]"), "how": json.loads(r["how_json"] or "[]"),
                 "need": r["need"], "review": r["review"], "updated_at": r["updated_at"]} for r in rows]

    def set_review(self, cid: str, phase_id: str, item_id: Optional[str], col: Optional[str], review: str) -> int:
        sql = "UPDATE cells SET review=?, updated_at=? WHERE case_id=? AND phase_id=?"
        args = [review, time.time(), cid, phase_id]
        if item_id:
            sql += " AND item_id=?"
            args.append(item_id)
        if col:
            sql += " AND col=?"
            args.append(col)
        with self._conn() as c:
            cur = c.execute(self._sql(sql), tuple(args))
        return cur.rowcount

    # --- events -------------------------------------------------------------
    def add_event(self, cid: str, kind: str, data: Optional[dict] = None) -> int:
        for _ in range(8):                                   # another worker may take the same seq
            try:
                with self._conn() as c:
                    r = c.execute(self._sql("SELECT COALESCE(MAX(seq),0) AS m FROM case_events WHERE case_id=?"),
                                  (cid,)).fetchone()
                    seq = int(r["m"]) + 1
                    c.execute(self._sql("INSERT INTO case_events(case_id,seq,ts,kind,data_json) VALUES(?,?,?,?,?)"),
                              (cid, seq, time.time(), kind, json.dumps(data or {}, ensure_ascii=False)))
                return seq
            except Exception:
                time.sleep(0.02)
        raise RuntimeError("could not record the event")

    def events_after(self, cid: str, after: int = 0, limit: int = 500) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(self._sql(
                "SELECT seq,ts,kind,data_json FROM case_events WHERE case_id=? AND seq>? ORDER BY seq LIMIT ?"),
                (cid, after, limit)).fetchall()
        return [{"seq": r["seq"], "ts": r["ts"], "kind": r["kind"], "data": json.loads(r["data_json"] or "{}")}
                for r in rows]

    # --- questions ----------------------------------------------------------
    def add_question(self, cid: str, item_id: str, phase_id: str, col: str, text: str) -> str:
        with self._conn() as c:
            r = c.execute(self._sql(
                "SELECT id FROM questions WHERE case_id=? AND item_id=? AND phase_id=? AND col=? AND status='open'"),
                (cid, item_id, phase_id, col)).fetchone()
            if r:
                return r["id"]
            qid = uuid.uuid4().hex[:10]
            c.execute(self._sql(
                "INSERT INTO questions(id,case_id,item_id,phase_id,col,text,status,answer,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)"), (qid, cid, item_id, phase_id, col, text, "open", "", time.time()))
        return qid

    def questions(self, cid: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(self._sql("SELECT * FROM questions WHERE case_id=? ORDER BY created_at"),
                             (cid,)).fetchall()
        return [{"id": r["id"], "item_id": r["item_id"], "phase_id": r["phase_id"], "column": r["col"],
                 "text": r["text"], "status": r["status"], "answer": r["answer"],
                 "created_at": r["created_at"]} for r in rows]

    def get_question(self, qid: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(self._sql("SELECT * FROM questions WHERE id=?"), (qid,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "case_id": r["case_id"], "item_id": r["item_id"], "phase_id": r["phase_id"],
                "column": r["col"], "text": r["text"], "status": r["status"], "answer": r["answer"]}

    def close_question(self, qid: str, status: str, answer: str = "") -> None:
        with self._conn() as c:
            c.execute(self._sql("UPDATE questions SET status=?, answer=? WHERE id=?"), (status, answer, qid))


@lru_cache(maxsize=1)
def store() -> CaseStore:
    return CaseStore()


def reset_for_tests() -> None:
    store.cache_clear()
