"""A request: the demands being gathered before a case exists.

A sheet (or a typed demand) is read into demands; what each one still lacks is worked out in code, from the use
case's required input fields. The person fills the gaps, asks the requester for them, or starts anyway; submitting hands
the demands to the engine through the same `create` step a sheet always used. Nothing here calls a model, and nothing
here decides what a field means: a demand is complete when every required field has text in it.

  start    read demands into a request (nothing runs)
  view     the demands, what each one is missing, and the fields missing in several at once
  set      give one demand's fields a value, or mark a missing field "ask the requester"
  fill     one value (or "ask the requester") for the same missing field of several demands, chosen by the person
  submit   hand the demands to the engine; a demand still incomplete is held by the engine's own check
  gaps     the missing information as a sheet to send back to the requesters

The scope of a shared value is always the person's choice: this never assumes that two demands share a department
or a sponsor.
"""

from __future__ import annotations

import csv
import io
from typing import Callable, Optional

from eawiki import completeness, usecases

MAX_VALUE = 4000
STEP_MAX = 5                  # up to this many open questions are asked one at a time; more are listed, and the person chooses how to go on
DRAFTING, SUBMITTED = "drafting", "submitted"


class RequestError(ValueError):
    """The input is wrong: say what."""


class RequestMissing(LookupError):
    """No such request, or no such demand in it."""


class RequestLocked(PermissionError):
    """The request was already submitted."""


class RequestIncomplete(PermissionError):
    """Required information is missing; the person may start anyway."""


def _spec(rq: dict) -> dict:
    spec = usecases.get(rq["use_case_id"])
    if not spec:
        raise RequestMissing(f"no use case '{rq['use_case_id']}'")
    return spec


def get(store, rid: str) -> dict:
    rq = store.get_request(rid)
    if not rq:
        raise RequestMissing("no such request")
    return rq


def _open(store, rid: str) -> dict:
    rq = get(store, rid)
    if rq["status"] != DRAFTING:
        raise RequestLocked("This request was already submitted.")
    return rq


def start(store, spec: dict, *, name: str, items: list[dict], files=(), unmatched=()) -> str:
    from eawiki.query import executor
    out = []
    for i, it in enumerate(items):
        it = dict(it)
        it["_id"] = str(it.get("_id") or executor._item_id(it, i, spec))
        it["_intake"] = {"declined": [], "set": {}, "from": {}, **(it.get("_intake") or {})}
        out.append(it)
    return store.create_request(spec.get("id", ""), name, out, {"files": list(files), "unmatched": list(unmatched)})


def view(store, rid: str) -> dict:
    rq = get(store, rid)
    spec = _spec(rq)
    inp = spec.get("input") or {}
    fields = completeness.input_fields(spec)
    title_field = inp.get("title_field") or "title"
    label = inp.get("item_label") or {"singular": "item", "plural": "items"}
    counts: dict = {}
    for it in rq["items"]:
        counts[it["_id"]] = counts.get(it["_id"], 0) + 1
    items = []
    for it in rq["items"]:
        miss = completeness.missing_fields(spec, it)
        meta = it.get("_intake") or {}
        problems = [f"Another {label['singular']} has the same ID, {it['_id']}."] if counts[it["_id"]] > 1 else []
        items.append({"id": it["_id"], "title": str(it.get(title_field) or it["_id"]),
                      "values": {f["name"]: str(it.get(f["name"]) or "") for f in fields},
                      "missing": miss, "declined": [m["name"] for m in miss if m["name"] in (meta.get("declined") or [])],
                      "set": dict(meta.get("set") or {}), "from": dict(meta.get("from") or {}), "problems": problems})
    groups = []
    for f in fields:
        ids = [i["id"] for i in items if any(m["name"] == f["name"] for m in i["missing"])]
        if len(ids) >= 2:
            groups.append({"field": f["name"], "label": f.get("label") or f["name"], "type": f.get("type") or "text",
                           "values": list(f.get("values") or []), "description": f.get("description") or "", "items": ids})
    complete = sum(1 for i in items if not i["missing"] and not i["problems"])
    questions = open_questions(fields, items)
    return {"id": rq["id"], "use_case_id": rq["use_case_id"], "name": rq["name"], "status": rq["status"], "case_id": rq["case_id"],
            "files": rq["meta"].get("files") or [], "unmatched": rq["meta"].get("unmatched") or [], "item_label": label,
            "fields": [{"name": f["name"], "label": f.get("label") or f["name"], "description": f.get("description") or "",
                        "type": f.get("type") or "text", "values": list(f.get("values") or []), "required": bool(f.get("required"))} for f in fields],
            "items": items, "groups": groups, "questions": questions, "stepwise": len(questions) <= STEP_MAX, "messages": rq["meta"].get("messages") or [], "pending": rq["meta"].get("pending"),
            "sources": [{k: x.get(k) for k in ("name", "kind", "chars", "truncated", "notes")} for x in rq["meta"].get("sources") or []],
            "summary": {"total": len(items), "complete": complete, "incomplete": len(items) - complete,
                        "problems": sum(1 for i in items if i["problems"])},
            "ready": bool(items) and complete == len(items)}


def open_questions(fields: list, items: list) -> list:
    """What is still to be asked, one entry per required field that is empty for some demand and not yet given up on for it, in the use
    case's field order: {field, label, description, type, options, items}. Pure code; the person decides how to go through them."""
    out = []
    for f in fields:
        ids = [i["id"] for i in items if any(m["name"] == f["name"] for m in i["missing"]) and f["name"] not in i["declined"]]
        if ids:
            out.append({"field": f["name"], "label": f.get("label") or f["name"], "description": f.get("description") or "",
                        "type": f.get("type") or "text", "options": list(f.get("values") or []) if f.get("type") == "enum" else [], "items": ids})
    return out


def _value(field: dict, raw) -> str:
    v = "" if raw is None else str(raw).strip()
    if len(v) > MAX_VALUE:
        raise RequestError(f"'{field.get('label') or field['name']}' is longer than {MAX_VALUE} characters.")
    vals = field.get("values") or []
    if field.get("type") == "enum" and v:
        hit = next((x for x in vals if x.lower() == v.lower()), None)
        if hit is None:
            raise RequestError(f"'{v}' is not one of: {', '.join(vals)}.")
        return hit
    return v


def _fields(spec: dict) -> dict:
    return {f["name"]: f for f in completeness.input_fields(spec)}


def _follow_id(spec: dict, it: dict, field: str, value: str) -> None:
    """A demand's id follows its id field."""
    if value and field == (spec.get("input") or {}).get("id_field"):
        it["_id"] = value


def _apply(it: dict, field: str, value: str, by: str = "you", quote: str = "", source: str = "") -> None:
    """Put a value in a field and record where it came from: "you" typed it, or "message" / "file" with the words it came from."""
    meta = it.setdefault("_intake", {"declined": [], "set": {}, "from": {}})
    it[field] = value
    meta.setdefault("from", {}).pop(field, None)
    if value:
        meta.setdefault("set", {})[field] = "you"
        if by != "you":
            meta["set"].pop(field, None)
            meta["from"][field] = {"by": by, "quote": quote, "source": source}
        meta["declined"] = [d for d in meta.get("declined") or [] if d != field]
    else:
        meta.setdefault("set", {}).pop(field, None)


def set_values(store, rid: str, item_id: str, values: Optional[dict], declined: Optional[list]) -> dict:
    """Give a demand's fields values, and say which of its missing fields to ask the requester for. `declined`, when given,
    replaces the list; a field that has a value cannot be declined."""
    rq = _open(store, rid)
    spec = _spec(rq)
    by = _fields(spec)
    it = next((x for x in rq["items"] if x["_id"] == item_id), None)
    if it is None:
        raise RequestMissing("no such demand in this request")
    values = values or {}
    clean = {}
    for name, raw in values.items():
        if name not in by:
            raise RequestError(f"'{name}' is not an input field of this use case.")
        clean[name] = _value(by[name], raw)
    if declined is not None:
        bad = [d for d in declined if d not in by]
        if bad:
            raise RequestError(f"'{bad[0]}' is not an input field of this use case.")
    for name, v in clean.items():
        _apply(it, name, v)
    meta = it.setdefault("_intake", {"declined": [], "set": {}})
    if declined is not None:
        meta["declined"] = [d for d in dict.fromkeys(declined) if completeness.is_empty(it.get(d))]
    for name, v in clean.items():
        _follow_id(spec, it, name, v)
    store.save_request(rid, items=rq["items"])
    return view(store, rid)


def fill(store, rid: str, field: str, items: list, value: Optional[str] = None, decline: bool = False) -> dict:
    """One value, or "ask the requester", for the same missing field of the demands the person picked. A demand that already
    has a value for the field is left alone."""
    rq = _open(store, rid)
    spec = _spec(rq)
    by = _fields(spec)
    if field not in by:
        raise RequestError(f"'{field}' is not an input field of this use case.")
    v = "" if decline else _value(by[field], value)
    if not decline and not v:
        raise RequestError("Give a value to fill in, or choose to ask the requesters.")
    ids = list(dict.fromkeys(items or []))
    known = {x["_id"] for x in rq["items"]}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise RequestMissing(f"no such demand in this request: {unknown[0]}")
    done, skipped = [], []
    for it in rq["items"]:
        if it["_id"] not in ids:
            continue
        if not completeness.is_empty(it.get(field)):
            skipped.append(it["_id"])
            continue
        if decline:
            meta = it.setdefault("_intake", {"declined": [], "set": {}})
            meta["declined"] = list(dict.fromkeys((meta.get("declined") or []) + [field]))
        else:
            _apply(it, field, v)
            _follow_id(spec, it, field, v)
        done.append(it["_id"])
    store.save_request(rid, items=rq["items"])
    return dict(view(store, rid), changed=done, skipped=skipped)


def apply_read(store, rid: str, assignments: list[dict], declines: Optional[list] = None) -> dict:
    """Put what the agent read into the demands. Each assignment is {id, field, value, quote}. Only an empty field is filled: a value
    from the sheet or typed by the person is never overwritten. `declines` is [(id, field)] to ask the requester for."""
    rq = _open(store, rid)
    spec = _spec(rq)
    by = _fields(spec)
    items = {x["_id"]: x for x in rq["items"]}
    changed, skipped = [], []
    for a in assignments:
        it, f = items.get(a["id"]), by.get(a["field"])
        if it is None or f is None:
            skipped.append(a)
            continue
        v = _value(f, a["value"])
        if not v or not completeness.is_empty(it.get(a["field"])):
            skipped.append(a)
            continue
        src = a.get("source") or ""
        _apply(it, a["field"], v, by="file" if src and src != "your message" else "message", quote=a.get("quote") or "", source=src)
        _follow_id(spec, it, a["field"], v)
        changed.append({"id": a["id"], "field": a["field"], "label": f.get("label") or f["name"], "value": v, "quote": a.get("quote") or "", "source": src})
    declined = []
    for iid, field in declines or []:
        it = items.get(iid)
        if it is not None and field in by and completeness.is_empty(it.get(field)):
            meta = it.setdefault("_intake", {"declined": [], "set": {}, "from": {}})
            meta["declined"] = list(dict.fromkeys((meta.get("declined") or []) + [field]))
            declined.append({"id": iid, "field": field, "label": by[field].get("label") or field})
    store.save_request(rid, items=rq["items"])
    return {"changed": changed, "skipped": skipped, "declined": declined}


def save_meta(store, rid: str, **kv) -> None:
    store.save_request(rid, meta=kv)


def submit(store, create: Callable, rid: str, allow_incomplete: bool = False) -> dict:
    """Hand the demands to the engine. `create(spec, items, name)` makes the case and starts it. A demand still incomplete goes
    in too when the person said to start anyway: the engine's own check holds it and returns it for information."""
    rq = _open(store, rid)
    spec = _spec(rq)
    v = view(store, rid)
    label = v["item_label"]
    if not v["items"]:
        raise RequestError(f"There are no {label['plural']} in this request.")
    problems = [p for i in v["items"] for p in i["problems"]]
    if problems:
        raise RequestError("Fix this first: " + " ".join(dict.fromkeys(problems)))
    n = v["summary"]["incomplete"]
    if n and not allow_incomplete:
        raise RequestIncomplete(f"{n} {label['singular'] if n == 1 else label['plural']} still {'misses' if n == 1 else 'miss'} required information. "
                                f"Fill it in, ask the requester{'' if n == 1 else 's'}, or start anyway: an incomplete {label['singular']} is held and returned for information.")
    cid = create(spec, [dict(it) for it in rq["items"]], rq["name"])
    store.save_request(rid, status=SUBMITTED, case_id=cid)
    return {"case_id": cid, "held": [i["id"] for i in v["items"] if i["missing"]]}


def _gap_table(v: dict) -> tuple[list, list, list]:
    """(header, rows, which cells are the missing ones): one row per incomplete demand, one column per field missing in any."""
    need = [f for f in v["fields"] if any(m["name"] == f["name"] for i in v["items"] for m in i["missing"])]
    head = ["Demand", "Title", "Missing"] + [f["label"] for f in need]
    rows, mask = [], []
    for i in v["items"]:
        if not i["missing"]:
            continue
        rows.append([i["id"], i["title"], "; ".join(m["label"] for m in i["missing"])] + [i["values"].get(f["name"], "") for f in need])
        mask.append([False, False, False] + [any(m["name"] == f["name"] for m in i["missing"]) for f in need])
    return head, rows, mask


def gaps_file(v: dict) -> tuple[bytes, str, str]:
    """The missing information as a sheet to send to the requesters: (bytes, file name, media type)."""
    head, rows, mask = _gap_table(v)
    name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in f"{v['name']} - missing information")[:90]
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(head)
        w.writerows(rows)
        return ("﻿" + buf.getvalue()).encode("utf-8"), name + ".csv", "text/csv; charset=utf-8"
    wb = Workbook()
    ws = wb.active
    ws.title = "Missing information"
    ws.append(head)
    for r in rows:
        ws.append(r)
    for c in ws[1]:
        c.font = Font(bold=True)
    fill_ = PatternFill("solid", fgColor="FBF0D9")
    for ri, row in enumerate(ws.iter_rows(min_row=2), 0):
        for ci, c in enumerate(row):
            c.alignment = Alignment(wrap_text=True, vertical="top")
            if mask[ri][ci]:
                c.fill = fill_
    for i, h in enumerate(head, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = 34 if i > 2 else 18
    ws.freeze_panes = "C2"
    guide = wb.create_sheet("Field guide")
    guide.append(["Field", "What it is", "Allowed values", "Required"])
    for f in v["fields"]:
        guide.append([f["label"], f["description"], "; ".join(f["values"]), "Yes" if f["required"] else "No"])
    for c in guide[1]:
        c.font = Font(bold=True)
    for col, w in zip("ABCD", (28, 80, 40, 10)):
        guide.column_dimensions[col].width = w
    for row in guide.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), name + ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
