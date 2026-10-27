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
import re
from typing import Callable, Optional

from eawiki.usecases import LOOKUP_FROM, LOOKUP_KINDS, LOOKUP_MATCH, MAX_LOOKUPS, PROFILE_GROUPS, RESULT_PREFIX

SOURCES = ("demand", "documents", "graph", "other_demands")
MAX_QUERIES = 3


def guidance_key(col: dict) -> str:
    """Changes exactly when something the plan depends on changes."""
    keep = {k: col.get(k) for k in ("name", "type", "values", "description", "how_to_resolve", "where_to_look",
                                    "look_in", "uses", "evidence_required", "lookups")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _words(s: str) -> set:
    return set(re.findall(r"[^\W_]{2,}", str(s or "").casefold()))


def _plural(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def resolve_docs(kind: str, docs: list[str]) -> list[str]:
    """The ingested documents a kind of source ("Application Catalog") stands for: a document whose
    name holds all the words of the kind. A document added later is matched the same way, so naming
    kinds, not files, never leaves a new document out."""
    kw = {_plural(w) for w in _words(kind)}
    if not kw:
        return []
    return [d for d in docs if kw <= {_plural(w) for w in _words(d)}]


def _lookup(raw: dict, docs: list[str]) -> Optional[dict]:
    if not isinstance(raw, dict) or not isinstance(raw.get("find"), str) or not raw["find"].strip():
        return None
    frm = raw.get("from")
    if not (frm in LOOKUP_FROM or (isinstance(frm, str) and frm.startswith(RESULT_PREFIX) and frm[len(RESULT_PREFIX):].strip())) \
            or raw.get("match") not in LOOKUP_MATCH:
        return None
    kinds = [k.strip() for k in (raw.get("in") or []) if isinstance(k, str) and k.strip()][:8]
    resolved = []
    for k in kinds:
        resolved += resolve_docs(k, docs)
    types = [t for t in (raw.get("types") or []) if t in LOOKUP_KINDS]
    return {"find": raw["find"].strip()[:200], "from": frm, "match": raw["match"], "in": kinds,
            "docs": list(dict.fromkeys(resolved)), "extract": str(raw.get("extract") or "")[:200], "types": types,
            "read_all": raw.get("read_all") is True}


def default_lookups(col: dict) -> list[dict]:
    return [{"find": (col.get("description") or col["name"]).split(". ")[0][:200], "from": "all_text",
             "match": "meaning", "in": [], "docs": [], "extract": "", "types": []}]


def default_plan(col: dict, docs: Optional[list[str]] = None) -> dict:
    docs = docs or []
    lks = [x for x in (_lookup(l, docs) for l in col.get("lookups") or []) if x] or default_lookups(col)
    pref = list(dict.fromkeys(list(col.get("look_in") or []) + [d for l in lks for d in l["docs"]]))
    return {"sources": ["demand", "documents", "graph"], "queries": ["{__text__}"], "lookups": lks,
            "documents": pref, "origin": "default"}


def _prompt(col: dict, fields: list[str], docs: list[str]) -> str:
    uses = ", ".join(col.get("uses") or []) or "(none)"
    return f"""You plan WHAT TO LOOK FOR to fill one property of an enterprise-architecture assessment for a demand. Output ONE JSON object, nothing else.

Property: {col['name']}  [{col.get('type', 'text')}{' of ' + ', '.join(col['values']) if col.get('values') else ''}]
Meaning: {col.get('description', '')}
How to decide it: {col.get('how_to_resolve', '') or '(not given)'}
Where the owner says to look (kinds of source): {col.get('where_to_look', '') or '(not given)'}
Documents the owner says to look in first: {', '.join(col.get('look_in') or []) or '(none named)'}
Already decided before this property (no search needed for these): {uses}

Before you plan: a first step lists what the demand MENTIONS, in groups: {', '.join(PROFILE_GROUPS)}. A lookup searches those mentions one at a time.

A LOOKUP says what to find, starting from which group of mentions, in which kinds of source, and how to match:
- "find": one sentence, what to find out
- "from": one of {', '.join(LOOKUP_FROM)}  (need = the demand's need and outcome; all_text = everything; other_demands = compare with the other demands)
- "match": name (the mention is a name to find, for example a system), meaning (find what the need or process corresponds to), or compare
- "in": kinds of source, as the owner names them (for example "Application Catalog"); leave empty if the steps do not say
- "extract": what to read from what is found

Ingested documents: {', '.join(docs) or '(none)'}
Sources you may use: demand (the demand's own fields: {', '.join(fields)}), documents, graph (entities the demand is about), other_demands.

Turn the steps into at most {MAX_LOOKUPS} lookups. One lookup per thing the steps say to check. Do not invent places the steps do not mention.

JSON: {{"sources": ["demand", "documents", ...], "lookups": [{{"find": "...", "from": "systems", "match": "name", "in": ["Application Catalog"], "extract": "which domain it belongs to"}}], "documents": ["<ingested document ids to search first>"]}}"""


def validate(raw, col: dict, fields: list[str], docs: list[str]) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    sources = [x for x in (raw.get("sources") or []) if x in SOURCES]
    lks = [x for x in (_lookup(l, docs) for l in (col.get("lookups") or raw.get("lookups") or [])) if x][:MAX_LOOKUPS]
    if not sources:
        sources = ["demand", "documents", "graph"] if lks else []
    if not sources:
        return None
    docset = {d.lower(): d for d in docs}
    named = [docset[d.lower()] for d in (raw.get("documents") or []) if isinstance(d, str) and d.lower() in docset]
    named = list(dict.fromkeys(list(col.get("look_in") or []) + [d for l in lks for d in l["docs"]] + named))
    if lks and "documents" not in sources and any(l["from"] != "other_demands" for l in lks):
        sources.append("documents")
    return {"sources": list(dict.fromkeys(sources)), "queries": ["{__text__}"], "lookups": lks or default_lookups(col),
            "documents": named, "origin": "model"}


def build_plan(col: dict, fields: list[str], docs: list[str], llm: Optional[Callable] = None,
               cache: Optional[dict] = None) -> dict:
    key = guidance_key(col) + hashlib.sha1("|".join(sorted(docs)).encode()).hexdigest()[:6]
    if cache is not None and key in cache:
        return cache[key]
    plan = None
    if col.get("lookups"):                                   # the owner wrote the lookups: no model call
        plan = default_plan(col, docs)
        plan["origin"] = "config"
    elif llm is not None:
        try:
            plan = validate(llm(_prompt(col, fields, docs)), col, fields, docs)
        except Exception:
            plan = None
    plan = plan or default_plan(col, docs)
    plan["key"] = key
    if cache is not None:
        cache[key] = plan
    return plan
