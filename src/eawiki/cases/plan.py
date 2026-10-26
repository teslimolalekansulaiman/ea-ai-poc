"""The retrieval plan for one property: where to look, and with what query.

A property's guidance (its description and how to resolve it) says in words what to consult; the
plan is that, as data. It is built once per property, kept with the guidance it came from, and
shown to the people who own the guidance, so what the agent will look at is never hidden.

  sources    demand        the item's own fields
             documents     passages of the ingested documents (the named ones first)
             graph         the entities the item is about, and what they are linked to
             other_demands the other items of the same sheet
  queries    short search texts; {field_name} is replaced by the item's field, {__text__} by all of them
  documents  document ids to search first

Meaning is the model's: one call reads the guidance and picks the sources. Structure is code: the
choice is checked against the menu above, the ingested document ids and the item's field names, so a
plan can never point at something that does not exist. With no model, a safe default is used.
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable, Optional

SOURCES = ("demand", "documents", "graph", "other_demands")
MAX_QUERIES = 3


def guidance_key(col: dict) -> str:
    """Changes exactly when something the plan depends on changes."""
    keep = {k: col.get(k) for k in ("name", "type", "values", "description", "how_to_resolve",
                                    "look_in", "uses", "evidence_required")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def default_plan(col: dict) -> dict:
    return {"sources": ["demand", "documents", "graph"], "queries": ["{__text__}"],
            "documents": list(col.get("look_in") or []), "origin": "default"}


def _prompt(col: dict, fields: list[str], docs: list[str]) -> str:
    return f"""You decide WHERE an assistant should look to fill one property of an enterprise-architecture assessment for a demand. Output ONE JSON object, nothing else.

Property: {col['name']}  [{col.get('type', 'text')}{' of ' + ', '.join(col['values']) if col.get('values') else ''}]
Meaning: {col.get('description', '')}
How to decide it: {col.get('how_to_resolve', '') or '(not given)'}
Documents the owner says to look in first: {', '.join(col.get('look_in') or []) or '(none named)'}

Sources you may choose (use only these names):
- demand: the demand's own fields ({', '.join(fields)})
- documents: passages of the ingested documents
- graph: the architecture entities the demand is about and what they are linked to
- other_demands: the other demands in the same sheet

Ingested documents: {', '.join(docs) or '(none)'}

Choose the sources this property really needs (not all of them), up to {MAX_QUERIES} short search queries (use {{field_name}} for the demand's fields, {{__text__}} for all of them), and the documents to search first (only from the ingested list).

JSON: {{"sources": ["demand", "documents", ...], "queries": ["..."], "documents": ["..."]}}"""


def validate(raw, col: dict, fields: list[str], docs: list[str]) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    sources = [s for s in (raw.get("sources") or []) if s in SOURCES]
    if not sources:
        return None
    fset = set(fields) | {"__text__"}
    queries = []
    for q in raw.get("queries") or []:
        if isinstance(q, str) and q.strip():
            import re
            names = set(re.findall(r"{(\w+)}", q))
            if names <= fset:
                queries.append(q.strip()[:300])
    docset = {d.lower(): d for d in docs}
    named = [docset[d.lower()] for d in (raw.get("documents") or []) if isinstance(d, str) and d.lower() in docset]
    named = list(dict.fromkeys(list(col.get("look_in") or []) + named))
    return {"sources": list(dict.fromkeys(sources)), "queries": queries[:MAX_QUERIES] or ["{__text__}"],
            "documents": named, "origin": "model"}


def build_plan(col: dict, fields: list[str], docs: list[str], llm: Optional[Callable] = None,
               cache: Optional[dict] = None) -> dict:
    key = guidance_key(col) + hashlib.sha1("|".join(sorted(docs)).encode()).hexdigest()[:6]
    if cache is not None and key in cache:
        return cache[key]
    plan = None
    if llm is not None:
        try:
            plan = validate(llm(_prompt(col, fields, docs)), col, fields, docs)
        except Exception:
            plan = None
    plan = plan or default_plan(col)
    plan["key"] = key
    if cache is not None:
        cache[key] = plan
    return plan
