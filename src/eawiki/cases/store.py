"""Persistence for cases: one row per case, one per cell, an event log and open questions.

Built on the same connection helper as `history` (SQLite by default, Postgres on Cloud Run), so
the portable SQL and the HISTORY_BACKEND switch are shared. A cell is saved the moment it is
decided, so the screen can show it filling in and a crash loses nothing.
"""

from __future__ import annotations

import json
import random
import sqlite3
import threading
import time
import uuid
from functools import lru_cache
from typing import Optional

from eawiki import history


REQUEST_ID = "_request"      # the "item" of a property worked out once for the whole request


class CaseStore(history._Store):
    _EVENT_LOCK = threading.Lock()                # one worker at a time takes the next event number

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
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS request_cells(
                case_id TEXT, phase_id TEXT, col TEXT, value_json TEXT, status TEXT, source TEXT, evidence_json TEXT,
                how_json TEXT, need TEXT, updated_at {r}, PRIMARY KEY(case_id, phase_id, col))"""))
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS case_events(
                case_id TEXT, seq INTEGER, ts {r}, kind TEXT, data_json TEXT,
                PRIMARY KEY(case_id, seq))"""))
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS questions(
                id TEXT PRIMARY KEY, case_id TEXT, item_id TEXT, phase_id TEXT, col TEXT,
                text TEXT, status TEXT, answer TEXT, created_at {r})"""))
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS documents(
                case_id TEXT, item_id TEXT, phase_id TEXT, status TEXT, doc_json TEXT, original_json TEXT,
                note TEXT, decided_at {r}, updated_at {r}, PRIMARY KEY(case_id, item_id, phase_id))"""))
            c.execute(self._sql(f"""CREATE TABLE IF NOT EXISTS intake_requests(
                id TEXT PRIMARY KEY, use_case_id TEXT, name TEXT, status TEXT, items_json TEXT, meta_json TEXT,
                case_id TEXT, created_at {r}, updated_at {r})"""))
            c.execute(self._sql("CREATE INDEX IF NOT EXISTS cases_uc ON cases(use_case_id, updated_at)"))
        self._add_column("questions", "meta_json", "TEXT")          # a store made before suggestions existed

    def _add_column(self, table: str, col: str, typ: str) -> None:
        try:
            with self._conn() as c:
                c.execute(self._sql(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
        except Exception:
            pass                                                       # it is already there

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

    def rename_case(self, cid: str, name: str) -> bool:
        with self._conn() as c:
            cur = c.execute(self._sql("UPDATE cases SET name=? WHERE id=?"), (name, cid))
        return cur.rowcount > 0

    def delete_case(self, cid: str) -> bool:
        with self._conn() as c:
            for t in ("cells", "case_events", "questions", "documents", "request_cells"):
                c.execute(self._sql(f"DELETE FROM {t} WHERE case_id=?"), (cid,))
            cur = c.execute(self._sql("DELETE FROM cases WHERE id=?"), (cid,))
        return cur.rowcount > 0

    # --- requests: what is being gathered before a case exists -------------------------------------------
    def create_request(self, use_case_id: str, name: str, items: list[dict], meta: Optional[dict] = None) -> str:
        rid = uuid.uuid4().hex[:12]
        now = time.time()
        with self._conn() as c:
            c.execute(self._sql(
                "INSERT INTO intake_requests(id,use_case_id,name,status,items_json,meta_json,case_id,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)"),
                (rid, use_case_id, name, "drafting", json.dumps(items, ensure_ascii=False), json.dumps(meta or {}, ensure_ascii=False), "", now, now))
        return rid

    def get_request(self, rid: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(self._sql("SELECT * FROM intake_requests WHERE id=?"), (rid,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "use_case_id": r["use_case_id"], "name": r["name"], "status": r["status"],
                "items": json.loads(r["items_json"] or "[]"), "meta": json.loads(r["meta_json"] or "{}"),
                "case_id": r["case_id"] or "", "created_at": r["created_at"], "updated_at": r["updated_at"]}

    def save_request(self, rid: str, *, items: Optional[list] = None, status: Optional[str] = None,
                     case_id: Optional[str] = None, meta: Optional[dict] = None) -> None:
        """`meta`, when given, is merged into the request's meta (a key set to None is removed)."""
        sets, vals = ["updated_at=?"], [time.time()]
        if meta is not None:
            cur = (self.get_request(rid) or {}).get("meta") or {}
            for k, v in meta.items():
                if v is None:
                    cur.pop(k, None)
                else:
                    cur[k] = v
            sets.append("meta_json=?")
            vals.append(json.dumps(cur, ensure_ascii=False))
        if items is not None:
            sets.append("items_json=?")
            vals.append(json.dumps(items, ensure_ascii=False))
        if status is not None:
            sets.append("status=?")
            vals.append(status)
        if case_id is not None:
            sets.append("case_id=?")
            vals.append(case_id)
        with self._conn() as c:
            c.execute(self._sql(f"UPDATE intake_requests SET {','.join(sets)} WHERE id=?"), (*vals, rid))

    # --- documents: a stage shown as one draft per demand, which an architect edits and approves ----------
    @staticmethod
    def _doc_row(r) -> dict:
        return {"item_id": r["item_id"], "phase_id": r["phase_id"], "status": r["status"], "doc": json.loads(r["doc_json"]),
                "original": json.loads(r["original_json"]), "note": r["note"] or "", "decided_at": r["decided_at"],
                "updated_at": r["updated_at"]}

    def documents(self, cid: str, phase_id: str) -> dict:
        """{item id: the saved document}. A demand with no row has an unedited draft, composed from its cells."""
        with self._conn() as c:
            rows = c.execute(self._sql("SELECT * FROM documents WHERE case_id=? AND phase_id=?"), (cid, phase_id)).fetchall()
        return {r["item_id"]: self._doc_row(r) for r in rows}

    def save_document(self, cid: str, item_id: str, phase_id: str, *, status: str, doc: dict, original: dict,
                      note: str = "", decided_at: Optional[float] = None) -> None:
        now = time.time()
        with self._conn() as c:
            c.execute(self._sql(
                "INSERT INTO documents(case_id,item_id,phase_id,status,doc_json,original_json,note,decided_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(case_id,item_id,phase_id) DO UPDATE SET status=excluded.status,"
                "doc_json=excluded.doc_json,original_json=excluded.original_json,note=excluded.note,"
                "decided_at=excluded.decided_at,updated_at=excluded.updated_at"),
                (cid, item_id, phase_id, status, json.dumps(doc, ensure_ascii=False), json.dumps(original, ensure_ascii=False),
                 note, decided_at, now))

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

    def save_request_cell(self, cid: str, phase_id: str, col: str, *, value, status: str, source: str = "model",
                          evidence=None, how=None, need: str = "") -> None:
        """A property worked out once for the whole request has no item: it is kept apart from the items' cells, so nothing that counts
        or lists an item's cells ever meets it."""
        now = time.time()
        with self._conn() as c:
            c.execute(self._sql(
                "INSERT INTO request_cells(case_id,phase_id,col,value_json,status,source,evidence_json,how_json,need,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(case_id,phase_id,col) DO UPDATE SET value_json=excluded.value_json,"
                "status=excluded.status,source=excluded.source,evidence_json=excluded.evidence_json,how_json=excluded.how_json,"
                "need=excluded.need,updated_at=excluded.updated_at"),
                (cid, phase_id, col, json.dumps(value, ensure_ascii=False), status, source,
                 json.dumps(evidence or [], ensure_ascii=False), json.dumps(how or [], ensure_ascii=False), need or "", now))

    def request_cells(self, cid: str, phase_id: str) -> dict:
        """{property: cell} of the properties worked out once for the whole request."""
        with self._conn() as c:
            rows = c.execute(self._sql("SELECT * FROM request_cells WHERE case_id=? AND phase_id=?"), (cid, phase_id)).fetchall()
        return {r["col"]: {"column": r["col"], "value": json.loads(r["value_json"]), "status": r["status"], "source": r["source"],
                           "evidence": json.loads(r["evidence_json"] or "[]"), "how": json.loads(r["how_json"] or "[]"),
                           "need": r["need"], "updated_at": r["updated_at"]} for r in rows}

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
        """Append an event with the next number for the case. Workers of this process take turns; another
        instance writing to the same database can still take the same number, so a clash is retried."""
        payload = json.dumps(data or {}, ensure_ascii=False)
        for attempt in range(30):
            try:
                with CaseStore._EVENT_LOCK, self._conn() as c:
                    r = c.execute(self._sql("SELECT COALESCE(MAX(seq),0) AS m FROM case_events WHERE case_id=?"),
                                  (cid,)).fetchone()
                    seq = int(r["m"]) + 1
                    c.execute(self._sql("INSERT INTO case_events(case_id,seq,ts,kind,data_json) VALUES(?,?,?,?,?)"),
                              (cid, seq, time.time(), kind, payload))
                return seq
            except Exception:
                time.sleep(0.01 + random.random() * 0.03 * (attempt + 1))
        raise RuntimeError("could not record the event")

    def last_event_ts(self, cid: str) -> float:
        with self._conn() as c:
            r = c.execute(self._sql("SELECT MAX(ts) AS t FROM case_events WHERE case_id=?"), (cid,)).fetchone()
        return float(r["t"] or 0) if r else 0.0

    def events_after(self, cid: str, after: int = 0, limit: int = 500) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(self._sql(
                "SELECT seq,ts,kind,data_json FROM case_events WHERE case_id=? AND seq>? ORDER BY seq LIMIT ?"),
                (cid, after, limit)).fetchall()
        return [{"seq": r["seq"], "ts": r["ts"], "kind": r["kind"], "data": json.loads(r["data_json"] or "{}")}
                for r in rows]

    # --- questions ----------------------------------------------------------
    def add_question(self, cid: str, item_id: str, phase_id: str, col: str, text: str,
                     meta: Optional[dict] = None) -> str:
        """Open a question for the architect. `meta` carries what the card shows besides the question:
        what is missing, where it looked, and the candidate answers the sources support."""
        mj = json.dumps(meta or {}, ensure_ascii=False)
        with self._conn() as c:
            r = c.execute(self._sql(
                "SELECT id FROM questions WHERE case_id=? AND item_id=? AND phase_id=? AND col=? AND status='open'"),
                (cid, item_id, phase_id, col)).fetchone()
            if r:                                                     # asked again after a re-run: keep the newer wording
                c.execute(self._sql("UPDATE questions SET text=?, meta_json=? WHERE id=?"), (text, mj, r["id"]))
                return r["id"]
            qid = uuid.uuid4().hex[:10]
            c.execute(self._sql(
                "INSERT INTO questions(id,case_id,item_id,phase_id,col,text,status,answer,created_at,meta_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)"), (qid, cid, item_id, phase_id, col, text, "open", "", time.time(), mj))
        return qid

    @staticmethod
    def _meta(r) -> dict:
        try:
            return json.loads(r["meta_json"] or "{}")
        except Exception:
            return {}

    def questions(self, cid: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(self._sql("SELECT * FROM questions WHERE case_id=? ORDER BY created_at"),
                             (cid,)).fetchall()
        return [{"id": r["id"], "item_id": r["item_id"], "phase_id": r["phase_id"], "column": r["col"],
                 "text": r["text"], "status": r["status"], "answer": r["answer"],
                 "created_at": r["created_at"], "meta": self._meta(r)} for r in rows]

    def get_question(self, qid: str) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(self._sql("SELECT * FROM questions WHERE id=?"), (qid,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "case_id": r["case_id"], "item_id": r["item_id"], "phase_id": r["phase_id"],
                "column": r["col"], "text": r["text"], "status": r["status"], "answer": r["answer"],
                "meta": self._meta(r)}

    def set_question_meta(self, qid: str, **fields) -> None:
        q = self.get_question(qid)
        if not q:
            return
        meta = dict(q["meta"], **fields)
        with self._conn() as c:
            c.execute(self._sql("UPDATE questions SET meta_json=? WHERE id=?"), (json.dumps(meta, ensure_ascii=False), qid))

    def close_question(self, qid: str, status: str, answer: str = "") -> None:
        with self._conn() as c:
            c.execute(self._sql("UPDATE questions SET status=?, answer=? WHERE id=?"), (status, answer, qid))


@lru_cache(maxsize=1)
def store() -> CaseStore:
    return CaseStore()


def reset_for_tests() -> None:
    store.cache_clear()
