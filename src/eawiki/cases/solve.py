"""Answer one property for one item, then check the answer in code.

The model reads only the evidence gathered for THIS property and returns a value, a status and the
ids it cited. Everything that can be checked is checked here, not trusted:

  * a cited id must be one of the evidence ids that were actually shown;
  * a value must fit the property's type and pick list;
  * a property that needs a cited source and has none is not answered: it becomes "needs input"
    and the question to ask is the property's own "info needed" line;
  * no model gives a confidence number.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from eawiki.cases import gather as gmod

NONE_WORDS = re.compile(r"^(None|No link found|Not identified)$", re.I)
NA_WORDS = ("Not assessed", "Not checked", "Not applicable", "No score")
STATUSES = ("answered", "needs_source", "needs_input")


def needs_evidence(col: dict) -> bool:
    return col.get("evidence_required") is not False


def not_assessed_value(col: dict):
    """What a property reads when the item failed the gate: the property's own 'not assessed'
    word where its pick list has one, else the plain phrase."""
    vals = col.get("values") or []
    for w in NA_WORDS:
        if w in vals:
            return [w] if col.get("type") == "list" else w
    return ["Not assessed"] if col.get("type") == "list" else "Not assessed"


def _prompt(col: dict, item: dict, spec: dict, ev: dict, decided: dict) -> str:
    t = col.get("type", "text") + (f" (one of: {', '.join(col['values'])})" if col.get("values") else "")
    done = "\n".join(f"  {k}: {v}" for k, v in decided.items()) or "  (nothing yet)"
    req = ("A cited source is REQUIRED: answer only if the evidence supports it, citing the ids; if it does not, "
           "return status needs_input and say what is needed.") if needs_evidence(col) else \
          ("A cited source is NOT required: you may decide from the demand's fields, a definition or a rule, "
           "and cite the demand fields you used.")
    return f"""You fill ONE property of an enterprise-architecture assessment for ONE demand. Output ONE JSON object, nothing else.

PROPERTY: {col['name']}  [{t}]
MEANING: {col.get('description') or '(not given)'}
HOW TO DECIDE IT: {col.get('how_to_resolve') or '(not given)'}
{req}
Never invent. Use the exact words of the pick list when there is one. Use "None" or "No link found" or "Not identified" only when you looked and found nothing.

ALREADY DECIDED FOR THIS DEMAND:
{done}

EVIDENCE:
{gmod.render(ev)}

JSON: {{"value": <{'a list of strings' if col.get('type') == 'list' else 'a string'}>, "status": "answered|needs_source|needs_input", "evidence": ["<id from the evidence>"], "needs": "<what is missing, or empty>", "note": "<one short sentence on how you decided>"}}"""


def _coerce(col: dict, value):
    """(value, problem). A list property holds a list; a pick list holds one of its words."""
    typ = col.get("type", "text")
    if typ == "list":
        if isinstance(value, str):
            value = [v.strip() for v in re.split(r"[;\n]", value) if v.strip()]
        if not isinstance(value, list):
            return [], "the value is not a list"
        return [str(v).strip() for v in value if str(v).strip()], ""
    if isinstance(value, list):
        value = "; ".join(str(v) for v in value)
    value = "" if value is None else str(value).strip()
    vals = col.get("values") or []
    if typ == "enum" and value:
        hit = next((v for v in vals if v.lower() == value.lower()), None)
        if hit:
            return hit, ""
        if NONE_WORDS.match(value):
            return value, ""
        return value, f"'{value}' is not one of: {', '.join(vals)}"
    return value, ""


def verify(col: dict, res, ev: dict) -> dict:
    """Turn the model's answer into a stored cell. Never raises."""
    how = ["Looked at: " + "; ".join(ev.get("used") or ["nothing"])]
    if not isinstance(res, dict):
        return {"value": "", "status": "needs_input", "evidence": [], "how": how,
                "need": col.get("info_needed") or f"No usable answer for '{col['name']}'.", "source": "model"}
    status = res.get("status") if res.get("status") in STATUSES else "answered"
    value, problem = _coerce(col, res.get("value"))
    evidence = [e for e in (res.get("evidence") or []) if isinstance(e, str) and e in ev.get("allowed", set())]
    need = str(res.get("needs") or "").strip()
    if problem and status == "answered":
        status, need = "needs_input", need or problem
    empty = value == "" or value == []
    if status == "answered" and empty:
        status = "needs_input"
    cited_blocks = [e for e in evidence if not e.startswith("demand:")]
    if status == "answered" and needs_evidence(col) and not evidence:
        status = "needs_input"
        need = col.get("info_needed") or f"No source found for '{col['name']}'. Provide it, or say where to look."
        how.append("The answer cited no source, and this property needs one.")
    if status != "answered":
        need = need or col.get("info_needed") or f"'{col['name']}' could not be decided from the evidence."
        value = [] if col.get("type") == "list" else ""
    note = str(res.get("note") or "").strip()
    if note:
        how.append("Model's note: " + note[:240])
    if status == "answered" and not cited_blocks and not evidence:
        how.append("No cited source: this rests on the demand, a definition or a rule.")
    return {"value": value, "status": status, "evidence": evidence, "how": how, "need": need if status != "answered" else "",
            "source": "model"}


def solve(col: dict, item: dict, spec: dict, ev: dict, decided: dict, llm: Callable) -> dict:
    try:
        res = llm(_prompt(col, item, spec, ev, decided))
    except Exception:
        res = None
    return verify(col, res, ev)


# ---- the gate ---------------------------------------------------------------------------
def gate(spec: dict, item: dict, llm: Callable, missing: list[str]) -> dict:
    """Is this a true demand? Required fields are checked by code; the intake questions by the model.
    Returns {outcome, reason}. The outcome is 'Yes', 'Not yet: return for information' or 'No: <type>'."""
    if missing:
        return {"outcome": "Not yet: return for information", "reason": "Missing: " + ", ".join(missing)}
    val = spec.get("validation") or {}
    if not val.get("enabled") or not (val.get("questions") or []):
        return {"outcome": "Yes", "reason": ""}
    qs = "\n".join(f"  {i + 1}. {q}" for i, q in enumerate(val["questions"]))
    prompt = f"""You check whether a request is a true demand before it is assessed. Output ONE JSON object, nothing else.

INTAKE QUESTIONS (all must be answered yes):
{qs}

THE REQUEST:
{gmod.item_text(spec, item)}

If every answer is yes, the outcome is "Yes". If the request is incomplete or too vague to assess, the outcome is "Not yet: return for information". If it is not a demand, the outcome is "No: <type>", where the type is incident, question or standard service.

JSON: {{"outcome": "Yes|Not yet: return for information|No: <type>", "reason": "<one short sentence>"}}"""
    try:
        out = llm(prompt)
    except Exception:
        out = None
    if not isinstance(out, dict):
        return {"outcome": "Not yet: return for information", "reason": "The intake check gave no answer."}
    o = str(out.get("outcome") or "").strip()
    if not (o == "Yes" or o.startswith("Not yet") or o.startswith("No:")):
        o = "Not yet: return for information"
    return {"outcome": o, "reason": str(out.get("reason") or "")[:240]}
