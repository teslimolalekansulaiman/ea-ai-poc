"""A stage shown as a document: one draft per demand, composed in code from the stage's cells.

A stage whose output mode is "document" is not read as a table. Its result is what an architect recommends for the
demand, so each demand gets a short document: the headline statement, a few key lines, and a section for every other
property. Nothing here is model output. The text is the cells' own, in the order the use case declares, so the document
and the table cannot disagree; the one model-written passage is whatever the use case names as the statement.

    "output": {"mode": "document", "document": {"statement": "<a text property>", "facts": ["<property>", ...]},
               "columns": [...]}

The tag beside the statement is the stage's result row tag. A property graded in code is left out (the grade is for the
table, not for a page that is going to be read and signed). What is still unconfirmed is listed from the open cells of this
stage and the stages before it; the sources are the citations property's.

The architect edits the draft as text, approves it, or returns it with a note. The first edit keeps the original, so the
record shows what was changed. An approved document is locked: running the stage again does not touch it.
"""

from __future__ import annotations

import html
import time
from typing import Optional

from eawiki.cases.engine import gate_column, phase_id

MODE = "document"
OPEN = ("needs_input", "needs_source")
TO_CONFIRM = "To confirm before approval"
EVIDENCE = "Evidence"
MAX_SECTIONS, MAX_FACTS, MAX_TEXT = 40, 12, 8000
STATUSES = ("draft", "approved", "returned")


def is_document(stage: dict) -> bool:
    return (stage.get("output") or {}).get("mode") == MODE


def settings(stage: dict) -> dict:
    return (stage.get("output") or {}).get("document") or {}


def _text(v) -> str:
    if isinstance(v, list):
        return "\n".join(str(x) for x in v if str(x).strip())
    return "" if v is None else str(v).strip()


def compose(spec: dict, stage: dict, item: dict, cells: dict, earlier_open: Optional[list] = None) -> dict:
    """The draft for one demand. `cells` is {property: cell} for this demand in this stage; `earlier_open` is
    [(label, need)] for what the stages before it left open."""
    cfg = settings(stage)
    cols = stage["output"]["columns"]
    tag_col = (stage.get("result") or {}).get("row_tag")
    stmt_col = cfg.get("statement") if cfg.get("statement") in {c["name"] for c in cols} else None
    fact_cols = [f for f in cfg.get("facts") or [] if f in {c["name"] for c in cols}]
    title_field = (spec.get("input") or {}).get("title_field") or "title"
    has = lambda name: _text((cells.get(name) or {}).get("value"))                  # noqa: E731
    body = has(stmt_col) if stmt_col else ""
    if not body:                                                                     # no statement property: the stage's own summary
        body = next((has(n) for n in stage.get("summary_columns") or [] if has(n)), "")
    facts = []
    if tag_col and has(tag_col):
        facts.append({"label": tag_col, "value": has(tag_col)})
    facts += [{"label": f, "value": has(f)} for f in fact_cols if has(f)]
    used = {stmt_col, tag_col, *fact_cols, gate_column(spec)}
    sections, sources = [], []
    for c in cols:
        if c["name"] in used or c.get("graded"):
            continue
        if c.get("type") == "citations":
            sources += [e for e in (cells.get(c["name"]) or {}).get("value") or [] if isinstance(e, str)]
            continue
        v = has(c["name"])
        if v and (cells.get(c["name"]) or {}).get("status") not in OPEN:
            sections.append({"title": c["name"], "body": v})
    open_ = [(c["name"], (cells.get(c["name"]) or {}).get("need", "")) for c in cols
             if (cells.get(c["name"]) or {}).get("status") in OPEN] + list(earlier_open or [])
    if open_:
        sections.append({"title": TO_CONFIRM, "body": "\n".join(f"? {n}" + (f": {need}" if need else "") for n, need in open_)})
    if sources:
        sections.append({"title": EVIDENCE, "body": "\n".join(dict.fromkeys(sources))})
    return {"title": str(item.get(title_field) or item.get("_id") or ""), "meta": str(item.get("_id") or ""),
            "rec": {"title": stage.get("name") or "Recommendation", "body": body}, "facts": facts, "sections": sections}


def clean(doc) -> dict:
    """The shape an edit may take: text only, bounded. Anything else is dropped, so a stored document can always be rendered."""
    if not isinstance(doc, dict):
        raise ValueError("A document is an object.")
    s = lambda v: v.strip()[:MAX_TEXT] if isinstance(v, str) else ""                # noqa: E731
    rec = doc.get("rec") if isinstance(doc.get("rec"), dict) else {}
    facts = [{"label": s(f.get("label")), "value": s(f.get("value"))} for f in doc.get("facts") or [] if isinstance(f, dict)]
    sections = [{"title": s(x.get("title")), "body": s(x.get("body"))} for x in doc.get("sections") or [] if isinstance(x, dict)]
    facts = [f for f in facts if f["label"] or f["value"]][:MAX_FACTS]
    sections = [x for x in sections if x["title"] or x["body"]][:MAX_SECTIONS]
    return {"title": s(doc.get("title")), "meta": s(doc.get("meta")), "rec": {"title": s(rec.get("title")), "body": s(rec.get("body"))},
            "facts": facts, "sections": sections}


def _earlier_open(store, case: dict, pid: str, item_id: str) -> list:
    out = []
    for st in case["spec"]["stages"]:
        if phase_id(st) == pid:
            break
        for c in store.cells(case["id"], phase_id(st)):
            if c["item_id"] == item_id and c["status"] in OPEN:
                out.append((c["column"], c.get("need", "")))
    return out


def _stage(case: dict, pid: str) -> dict:
    stage = next((s for s in case["spec"]["stages"] if phase_id(s) == pid), None)
    if stage is None or not is_document(stage):
        raise LookupError("This phase is not shown as documents.")
    return stage


def listing(store, case: dict, pid: str) -> list[dict]:
    """One entry per demand that has results in this phase: its document as it stands, and where it is in review."""
    stage = _stage(case, pid)
    cid = case["id"]
    by: dict = {}
    for c in store.cells(cid, pid):
        by.setdefault(c["item_id"], {})[c["column"]] = c
    saved = store.documents(cid, pid)
    out = []
    for it in case["items"]:
        cells = by.get(it["_id"])
        if not cells:
            continue
        draft = compose(case["spec"], stage, it, cells, _earlier_open(store, case, pid, it["_id"]))
        sv = saved.get(it["_id"])
        out.append({"item_id": it["_id"], "title": draft["title"], "status": sv["status"] if sv else "draft",
                    "doc": sv["doc"] if sv else draft, "original": sv["original"] if sv else draft,
                    "edited": bool(sv and sv["doc"] != sv["original"]), "note": sv["note"] if sv else "",
                    "decided_at": sv["decided_at"] if sv else None,
                    "stale": bool(sv and sv["status"] != "approved" and draft != sv["original"])})
    return out


def _entry(store, case, pid, item_id) -> dict:
    e = next((x for x in listing(store, case, pid) if x["item_id"] == item_id), None)
    if e is None:
        raise LookupError("No results for that item in this phase.")
    return e


def edit(store, case: dict, pid: str, item_id: str, doc) -> dict:
    """Save the architect's text. The first edit keeps the draft it started from."""
    e = _entry(store, case, pid, item_id)
    if e["status"] == "approved":
        raise PermissionError("This recommendation is approved and locked.")
    store.save_document(case["id"], item_id, pid, status="draft", doc=clean(doc), original=e["original"])
    return _entry(store, case, pid, item_id)


def decide(store, case: dict, pid: str, item_id: str, action: str, note: str = "") -> dict:
    """approve, return (with a note) or reopen a returned one. When every demand's document is approved, the phase is."""
    e = _entry(store, case, pid, item_id)
    phase = case["state"].get("phases", {}).get(pid, {}).get("status")
    if action not in ("approve", "return", "reopen"):
        raise ValueError("action must be approve, return or reopen")
    if e["status"] == "approved":
        raise PermissionError("This recommendation is approved and locked.")
    if phase not in ("review", "approved"):
        raise PermissionError("The phase is not finished yet.")
    note = (note or "").strip()
    if action == "return" and not note:
        raise ValueError("Say what should change before it can be approved.")
    status = {"approve": "approved", "return": "returned", "reopen": "draft"}[action]
    if action == "reopen" and e["status"] != "returned":
        raise ValueError("Only a returned recommendation can be reopened.")
    store.save_document(case["id"], item_id, pid, status=status, doc=e["doc"], original=e["original"],
                        note=note if action == "return" else "", decided_at=time.time() if action == "approve" else None)
    if action == "approve" and all(x["status"] == "approved" or x["item_id"] == item_id for x in listing(store, case, pid)):
        store.set_phase(case["id"], pid, status="approved", approved=True)
    return _entry(store, case, pid, item_id)


def render_html(entry: dict) -> str:
    """The document as a self-contained page, for download. It opens in a browser and in Word."""
    d, e = entry["doc"], html.escape
    lines = [f"<h1>{e(d['title'])}</h1>", f"<p>{e(d['meta'])} · {e(entry['status'].title())}</p>",
             f"<h2>{e(d['rec']['title'])}</h2><p><b>{e(d['rec']['body'])}</b></p>"]
    lines += [f"<p>{e(f['label'])}: <b>{e(f['value'])}</b></p>" for f in d["facts"]]
    for s in d["sections"]:
        lines.append(f"<h2>{e(s['title'])}</h2>" + "".join(f"<p>{e(ln)}</p>" for ln in s["body"].splitlines() if ln.strip()))
    if entry["status"] != "approved":
        lines.append("<p><i>Draft. Nothing in it is a decision until it is approved.</i></p>")
    return ('<!doctype html><html><head><meta charset="utf-8"><title>' + e(d["title"]) + "</title></head><body>" + "".join(lines) + "</body></html>")
