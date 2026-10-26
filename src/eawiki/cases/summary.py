"""What the screen shows about a case, computed from its cells and the use case's `result` settings.

Nothing here is model output. The status chips, the row tags, the headline numbers, the list of
decisions and the suggested questions are all read off the stored cells by rules the use case
declares, so the screen and the table can never disagree.

A stage may carry:
  "result": {
     "row_tag": "Priority",                                   the property shown as each item's tag
     "tag_order": ["Fast-track", "Standard", "Backlog"],      most important first
     "kpis": [{"label": "Fast-track", "column": "Priority", "equals": "Fast-track"},
              {"label": "Duplicates", "column": "Is duplicate", "in": ["Yes", "Possible"]}],
     "decisions": [{"when": {"column": "Is duplicate", "in": ["Yes"], "filled": "Duplicate demand number (in the sheet)"},
                    "text": "Duplicate of {Duplicate demand number (in the sheet)}: group the demands and assess once."}],
     "questions": [{"text": "Why is {top_item} {top_tag}?", "if": "top"}, {"text": "...", "if": "returned"}]
  }
"""

from __future__ import annotations

import re

from eawiki.cases.engine import gate_column, phase_id
from eawiki.cases.solve import NONE_WORDS

NA_WORDS = {"not assessed", "not checked", "not applicable", "no score"}


def _txt(v) -> str:
    return "; ".join(map(str, v)) if isinstance(v, list) else ("" if v is None else str(v))


def display_status(spec: dict, cell: dict) -> str:
    """The chip a cell shows: answered, none, na, confirm, user, needs_input, needs_source, ret_in, ret_no, blank."""
    st = cell["status"]
    if st == "not_assessed":
        return "na"
    if st in ("needs_input", "needs_source", "user"):
        return st
    v = _txt(cell["value"]).strip()
    if cell["column"] == gate_column(spec):
        return "answered" if v == "Yes" else ("ret_in" if v.startswith("Not yet") else "ret_no")
    if not v:
        return "blank"
    if v.lower() in NA_WORDS:
        return "na"
    if NONE_WORDS.match(v):
        return "none"
    if v in ("Possible", "Needs confirmation"):
        return "confirm"
    return "answered"


def _matches(when: dict, vals: dict) -> bool:
    v = _txt(vals.get(when.get("column"), "")).strip()
    if "equals" in when and v != when["equals"]:
        return False
    if "in" in when and v not in when["in"]:
        return False
    if when.get("filled") and not _txt(vals.get(when["filled"], "")).strip():
        return False
    return True


def _fill(text: str, vals: dict) -> str:
    return re.sub(r"{([^{}]+)}", lambda m: _txt(vals.get(m.group(1), "")) or "?", text)


def phase_summary(spec: dict, stage: dict, cells: list[dict], items: list[dict], questions: list[dict]) -> dict:
    pid = phase_id(stage)
    cfg = stage.get("result") or {}
    by_item: dict = {}
    for c in cells:
        if c["phase_id"] == pid:
            by_item.setdefault(c["item_id"], {})[c["column"]] = c
    gname = gate_column(spec)
    has_gate = any(c["name"] == gname for c in stage["output"]["columns"])
    titles = {it["_id"]: it.get(((spec.get("input") or {}).get("title_field")) or "title") or it["_id"] for it in items}
    rows, returned, assessed = [], [], []
    for it in items:
        cs = by_item.get(it["_id"])
        if not cs:
            continue
        vals = {k: c["value"] for k, c in cs.items()}
        out = _txt(vals.get(gname)).strip() if has_gate else "Yes"
        tag = _txt(vals.get(cfg.get("row_tag", ""), "")).strip() if cfg.get("row_tag") else ""
        row = {"id": it["_id"], "title": titles.get(it["_id"]), "gate": out,
               "tag": tag, "tag_status": display_status(spec, cs[cfg["row_tag"]]) if cfg.get("row_tag") in cs else "",
               "done": len(cs), "total": len(stage["output"]["columns"])}
        rows.append(row)
        if out == "Yes":
            assessed.append(it["_id"])
        else:
            how = (cs.get(gname) or {}).get("how") or [""]
            returned.append({"id": it["_id"], "title": titles.get(it["_id"]), "outcome": out, "reason": how[0]})
    kpis = []
    for k in cfg.get("kpis") or []:
        n = sum(1 for iid in assessed if _matches(k, {c: cc["value"] for c, cc in by_item[iid].items()}))
        kpis.append({"label": k["label"], "value": n})
    open_q = {(q["item_id"], q["column"]) for q in questions if q["status"] == "open" and q["phase_id"] == pid}
    decisions = []
    for iid in assessed:
        vals = {c: cc["value"] for c, cc in by_item[iid].items()}
        for rule in cfg.get("decisions") or []:
            if _matches(rule["when"], vals):
                decisions.append({"item": iid, "kind": "rule", "text": _fill(rule["text"], vals)})
        for c, cc in by_item[iid].items():
            if display_status(spec, cc) == "confirm" and (iid, c) not in open_q:
                decisions.append({"item": iid, "kind": "confirm", "text": f"Confirm {c}: {_txt(cc['value'])}."})
    order = cfg.get("tag_order") or []
    ranked = sorted((r for r in rows if r["id"] in assessed and r["tag"] in order), key=lambda r: order.index(r["tag"]))
    top = ranked[0] if ranked else None
    flags = {"returned": bool(returned), "decisions": bool(decisions), "top": bool(top), "always": True}
    suggested = []
    for q in cfg.get("questions") or []:
        if flags.get(q.get("if", "always")):
            suggested.append(_fill(q["text"], {"top_item": top["id"] if top else "", "top_tag": top["tag"] if top else ""}))
    return {"phase": pid, "name": stage.get("name"), "rows": rows, "assessed": len(assessed), "total": len(items),
            "returned": returned, "kpis": kpis, "decisions": decisions, "suggested": suggested,
            "open_questions": len(open_q)}
