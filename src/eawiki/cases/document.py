"""A stage shown as a document: one draft per demand, composed in code from the stage's cells.

A stage whose output mode is "document" is not read as a table. Its result is what an architect recommends for the
demand, so each demand gets a short document: the headline statement, a few key lines, and a section for every other
property. Nothing here is model output. The text is the cells' own, in the order the use case declares, so the document
and the table cannot disagree; the one model-written passage is whatever the use case names as the statement.

    "output": {"mode": "document", "document": {"statement": "<a text property>", "facts": ["<property>", ...],
                                                "internal": ["<property>", ...]},
               "columns": [...]}

`internal` names the properties that are for the architect and not part of what is sent: the draft keeps their sections apart,
after the message, together with what is still to confirm and the sources. The download holds the message only.

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

from eawiki.cases import groups as grpmod
from eawiki.cases.engine import gate_column, phase_id
from eawiki.cases.store import REQUEST_ID

MODE = "document"
OPEN = ("needs_input", "needs_source")
TO_CONFIRM = "To confirm before approval"
EVIDENCE = "Evidence"
MAX_SECTIONS, MAX_FACTS, MAX_TEXT = 600, 12, 8000
COMPACT_ABOVE = 3             # more open items than this are listed by name, not one line of guidance each
STATUSES = ("draft", "approved", "returned")


def is_document(stage: dict) -> bool:
    return (stage.get("output") or {}).get("mode") == MODE


def settings(stage: dict) -> dict:
    return (stage.get("output") or {}).get("document") or {}


def is_request(stage: dict) -> bool:
    """One draft for the whole request, with a section for each item, instead of one draft per item."""
    return settings(stage).get("scope") == "request"


def _text(v) -> str:
    if isinstance(v, list):
        return "\n".join(str(x) for x in v if str(x).strip())
    return "" if v is None else str(v).strip()


def to_confirm_lines(here: list, earlier: list) -> list:
    """What is still open, as lines starting with "?". A few open items get a line each with what is needed; many are listed by name,
    so the list does not become a wall of guidance. [(name, need)] for this stage and for the stages before it."""
    one = lambda n, need: f"? {n}" + (f": {need}" if need else "")                      # noqa: E731
    if len(here) + len(earlier) <= COMPACT_ABOVE:
        return [one(n, need) for n, need in here + earlier]
    out = [one(n, need) for n, need in here] if len(here) <= COMPACT_ABOVE else \
        ([f"? Not settled in this phase ({len(here)}): " + "; ".join(n for n, _ in here)] if here else [])
    if earlier:
        out.append(f"? Still open from the earlier phases ({len(earlier)}): " + "; ".join(n for n, _ in earlier))
    return out


def compose(spec: dict, stage: dict, item: dict, cells: dict, earlier_open: Optional[list] = None) -> dict:
    """The draft for one demand. `cells` is {property: cell} for this demand in this stage; `earlier_open` is
    [(label, need)] for what the stages before it left open."""
    cfg = settings(stage)
    cols = stage["output"]["columns"]
    tag_col = (stage.get("result") or {}).get("row_tag")
    stmt_col = cfg.get("statement") if cfg.get("statement") in {c["name"] for c in cols} else None
    apart = cfg.get("apart") is not False                                            # False: nothing is kept for the architect: no findings, no open list, no sources
    internal = set(cfg.get("internal") or []) if apart else set()
    fact_cols = [f for f in dict.fromkeys(cfg.get("facts") or []) if f in {c["name"] for c in cols} and f != tag_col]       # the tag opens the key lines already: never twice
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
            sections.append({"title": c["name"], "body": v, "column": c["name"], **({"internal": True} if c["name"] in internal else {})})      # the column is what "how it was decided" is read from
    here = [(c["name"], (cells.get(c["name"]) or {}).get("need", "")) for c in cols if (cells.get(c["name"]) or {}).get("status") in OPEN]
    lines = to_confirm_lines(here, list(earlier_open or []))
    keep = {"internal": True} if internal else {}                                    # with a message kept apart, what is open and the sources are the architect's too
    if lines and apart:
        sections.append({"title": TO_CONFIRM, "body": "\n".join(lines), **keep})
    if sources and apart:
        sections.append({"title": EVIDENCE, "body": "\n".join(dict.fromkeys(sources)), **keep})
    sections.sort(key=lambda x: bool(x.get("internal")))                              # the message's sections first, then the architect's (a stable sort)
    return {"title": str(item.get(title_field) or item.get("_id") or ""), "meta": str(item.get("_id") or ""),
            "rec": {"title": stage.get("name") or "Recommendation", "body": body, "column": stmt_col or ""}, "facts": facts, "sections": sections}


def compose_request(spec: dict, stage: dict, case: dict, held: dict, request_cells: dict, earlier_open: dict, gates: dict) -> dict:
    """The one draft for a whole request. It opens with the text written once for the request, then a section for each item: the items
    that are handled together first, under a heading that names the group, the lead first, then the others in the order they came; an
    item that did not pass the first check last, as returned. What is for the architect comes after, apart: each item's findings,
    what is still open (and where the answers about who is combined did not agree) and the sources."""
    cfg = settings(stage)
    cols = stage["output"]["columns"]
    names = {c["name"] for c in cols}
    title_field = (spec.get("input") or {}).get("title_field") or "title"
    over, item_col = cfg.get("statement"), cfg.get("item_text")
    keep_apart = cfg.get("apart") is not False                                        # False: the draft is the message and nothing else
    internal = [f for f in cfg.get("internal") or [] if f in names] if keep_apart else []
    have = {k[0] for k in held}
    assessed = [it for it in case["items"] if it["_id"] in have]
    returned = [it for it in case["items"] if it["_id"] not in have]
    gs = grpmod.of_stage(stage, assessed, held)
    grouped = [m for g in gs for m in g["members"]]
    order = grouped + [it["_id"] for it in assessed if it["_id"] not in grouped]
    label = {m: "Combined: " + ", ".join(g["members"]) for g in gs for m in g["members"]}
    by_id = {it["_id"]: it for it in case["items"]}
    name_of = lambda i: f"{i} · {by_id[i].get(title_field) or i}"                      # noqa: E731
    val = lambda i, c: _text((held.get((i, c)) or {}).get("value"))                      # noqa: E731
    message, apart = [], []
    for i in order:
        cell = held.get((i, item_col)) or {}
        body = val(i, item_col) if cell.get("status") not in OPEN else ""
        if not body:
            body = "Not written yet" + (f": {cell['need']}" if cell.get("need") else ".")
        message.append({"title": name_of(i), "body": body, "column": item_col, "item": i, **({"group": label[i]} if i in label else {})})
    for it in returned:
        message.append({"title": name_of(it["_id"]), "body": "Not assessed further. " + (gates.get(it["_id"]) or "It did not pass the first check, and goes back to the requester."),
                        "item": it["_id"]})
    for i in order:
        for f in internal:
            if val(i, f):
                apart.append({"title": f"{i} · {f}", "body": val(i, f), "column": f, "item": i, "internal": True})
    lines = []
    for i in order:
        here = [(c["name"], (held.get((i, c["name"])) or {}).get("need", "")) for c in cols if (held.get((i, c["name"])) or {}).get("status") in OPEN]
        lines += [f"? {i}: {ln[2:]}" for ln in to_confirm_lines(here, list(earlier_open.get(i) or []))]
    lines += [f"? {n}: {c.get('need') or 'not written yet'}" for n, c in request_cells.items() if c["status"] in OPEN or not _text(c["value"])]
    lines += [f"? {b} did not name {a} as a match, though {a} named {b}: confirm that they belong together." for g in gs for a, b in g["disagree"]]
    if lines and keep_apart:
        apart.append({"title": TO_CONFIRM, "body": "\n".join(lines), "internal": True})
    sources = [e for c in cols if c.get("type") == "citations" for i in order for e in (held.get((i, c["name"])) or {}).get("value") or [] if isinstance(e, str)]
    if sources and keep_apart:
        apart.append({"title": EVIDENCE, "body": "\n".join(dict.fromkeys(sources)), "internal": True})
    n = len(case["items"])
    return {"title": case["name"], "meta": f"{n} demand{'s' if n != 1 else ''}" + (f", {len(gs)} handled together" if gs else ""),
            "rec": {"title": f"{stage.get('name') or 'Recommendation'} for this request", "body": _text((request_cells.get(over) or {}).get("value")) if over else "",
                    **({"column": over} if over else {})},
            "facts": [], "sections": message + apart}


def clean(doc) -> dict:
    """The shape an edit may take: text only, bounded. Anything else is dropped, so a stored document can always be rendered."""
    if not isinstance(doc, dict):
        raise ValueError("A document is an object.")
    s = lambda v: v.strip()[:MAX_TEXT] if isinstance(v, str) else ""                # noqa: E731
    col = lambda x: {k: x[k].strip()[:200] for k in ("column", "item", "group") if isinstance(x.get(k), str) and x[k].strip()}      # noqa: E731
    rec = doc.get("rec") if isinstance(doc.get("rec"), dict) else {}
    facts = [{"label": s(f.get("label")), "value": s(f.get("value"))} for f in doc.get("facts") or [] if isinstance(f, dict)]
    sections = [{"title": s(x.get("title")), "body": s(x.get("body")), **col(x), **({"internal": True} if x.get("internal") is True else {})}
                for x in doc.get("sections") or [] if isinstance(x, dict)]
    facts = [f for f in facts if f["label"] or f["value"]][:MAX_FACTS]
    sections = [x for x in sections if x["title"] or x["body"]][:MAX_SECTIONS]
    return {"title": s(doc.get("title")), "meta": s(doc.get("meta")), "rec": {"title": s(rec.get("title")), "body": s(rec.get("body")), **col(rec)},
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
    if is_request(stage):
        return _request_listing(store, case, pid, stage)
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


def _request_listing(store, case: dict, pid: str, stage: dict) -> list[dict]:
    """The single entry of a stage shown as one draft for the whole request."""
    cid = case["id"]
    held = {(c["item_id"], c["column"]): c for c in store.cells(cid, pid)}
    if not held:
        return []
    spec = case["spec"]
    first = phase_id(spec["stages"][0])
    gates = {c["item_id"]: _text(c["value"]) for c in store.cells(cid, first) if c["column"] == gate_column(spec) and c["item_id"] not in {k[0] for k in held}}
    earlier = {it["_id"]: _earlier_open(store, case, pid, it["_id"]) for it in case["items"]}
    draft = compose_request(spec, stage, case, held, store.request_cells(cid, pid), earlier, gates)
    sv = store.documents(cid, pid).get(REQUEST_ID)
    return [{"item_id": REQUEST_ID, "title": draft["title"], "status": sv["status"] if sv else "draft",
             "doc": sv["doc"] if sv else draft, "original": sv["original"] if sv else draft,
             "edited": bool(sv and sv["doc"] != sv["original"]), "note": sv["note"] if sv else "",
             "decided_at": sv["decided_at"] if sv else None,
             "stale": bool(sv and sv["status"] != "approved" and draft != sv["original"])}]


def _entry(store, case, pid, item_id) -> dict:
    e = next((x for x in listing(store, case, pid) if x["item_id"] == item_id), None)
    if e is None:
        raise LookupError("No results for that item in this phase.")
    return e


def _shown(v) -> str:
    return "; ".join(str(x) for x in v) if isinstance(v, list) else ("" if v is None else str(v))


def trail(store, case: dict, pid: str, item_id: str) -> dict:
    """How each answer in the draft was decided, from what the engine recorded: for every property of the stage, what was searched, the
    passages the model was given, the sources it cited, its one-line note, and what it built on from earlier answers.
    {columns: {name: {status, source, need, how, evidence}}, built_on: {"decided:<id>": the earlier answer}}."""
    _stage(case, pid)
    cid = case["id"]
    if item_id == REQUEST_ID:                                  # the text written once for the request: it has no earlier answers of its own
        req = store.request_cells(cid, pid)
        if not req:
            raise LookupError("Nothing was written for the request in this phase.")
        return {"columns": {n: {"status": c["status"], "source": c.get("source") or "", "need": c.get("need") or "", "how": list(c.get("how") or []),
                                "evidence": [e for e in c.get("evidence") or [] if isinstance(e, str)]} for n, c in req.items()}, "built_on": {}}
    cells = {c["column"]: c for c in store.cells(cid, pid) if c["item_id"] == item_id}
    if not cells:
        raise LookupError("No results for that item in this phase.")
    earlier = {}
    for st in case["spec"]["stages"]:
        if phase_id(st) == pid:
            break
        for c in store.cells(cid, phase_id(st)):
            if c["item_id"] == item_id and c["status"] != "not_assessed":
                earlier[f"{st.get('name') or phase_id(st)} / {c['column']}"] = _shown(c["value"])
    built = {}
    cols = {}
    for name, c in cells.items():
        ev = [e for e in c.get("evidence") or [] if isinstance(e, str)]
        for e in ev:
            if e.startswith("decided:"):
                key = e[len("decided:"):]
                built[e] = earlier.get(key) or (_shown(cells[key]["value"]) if key in cells else "")
        cols[name] = {"status": c["status"], "source": c.get("source") or "", "need": c.get("need") or "", "how": list(c.get("how") or []), "evidence": ev}
    return {"columns": cols, "built_on": built}


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


def render_html(entry: dict, include_internal: bool = False) -> str:
    """The document as a self-contained page, for download. It opens in a browser and in Word. What is for the architect and not sent
    is left out unless asked for."""
    d, e = entry["doc"], html.escape
    lines = [f"<h1>{e(d['title'])}</h1>", f"<p>{e(d['meta'])} · {e(entry['status'].title())}</p>",
             f"<h2>{e(d['rec']['title'])}</h2><p><b>{e(d['rec']['body'])}</b></p>"]
    lines += [f"<p>{e(f['label'])}: <b>{e(f['value'])}</b></p>" for f in d["facts"]]
    group = None
    for s in d["sections"]:
        if s.get("internal") and not include_internal:
            continue
        if s.get("group") != group:
            group = s.get("group")
            if group:
                lines.append(f"<h2>{e(group)}</h2>")
        lines.append(f"<h2>{e(s['title'])}</h2>" + "".join(f"<p>{e(ln)}</p>" for ln in s["body"].splitlines() if ln.strip()))
    if entry["status"] != "approved":
        lines.append("<p><i>Draft. Nothing in it is a decision until it is approved.</i></p>")
    return ('<!doctype html><html><head><meta charset="utf-8"><title>' + e(d["title"]) + "</title></head><body>" + "".join(lines) + "</body></html>")
