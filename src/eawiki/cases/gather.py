"""Run a retrieval plan for one item and return labelled evidence.

Every piece of evidence carries an id the answer may cite, and `allowed` is the set of those ids:
the check that a cited source is real is done against it, in code.

  demand:<field>   one of the item's own fields
  demand:<item id> another item of the sheet
  <block id>       a passage of an ingested document
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

BLOCK_CHARS = 1100          # a table row or paragraph is read whole, not cut to a sentence
MAX_BLOCKS = 8
MAX_OTHERS = 12


@dataclass
class Tools:
    search: Callable[[str, int, Optional[list]], list]          # (query, k, docs) -> blocks
    blocks_by_ids: Callable[[list], list]
    link: Callable[[str], Optional[dict]]                       # item text -> linked entities
    graph_facts: Callable[[list], dict]                         # entity ids -> {facts, block_ids}
    llm_json: Callable[[str], Optional[dict]]
    doc_ids: Callable[[], list]


def item_text(spec: dict, item: dict) -> str:
    from eawiki.query import executor
    return executor._item_text(spec, item)


def labelled_fields(spec: dict, item: dict) -> dict:
    out = {}
    for f in (spec.get("input") or {}).get("item_fields") or []:
        v = str(item.get(f["name"]) or "").strip()
        if v:
            out[f["name"]] = (f.get("label") or f["name"], v)
    return out


def _fill(template: str, item: dict, text: str) -> str:
    d = defaultdict(str, {k: str(v) for k, v in item.items() if not str(k).startswith("_")})
    d["__text__"] = text
    try:
        return template.format_map(d)
    except Exception:
        return text


def with_hint(plan: dict, hint: dict) -> dict:
    """The plan for one cell when the architect said where to look: their document (if they named
    one) is searched alone, and what they wrote about where in it leads the search wording."""
    p = dict(plan)
    p["sources"] = list(dict.fromkeys(list(plan["sources"]) + ["documents"]))
    if hint.get("document"):
        p["documents"] = [hint["document"]]
    where = (hint.get("where") or "").strip()
    p["queries"] = ([where] if where else []) + list(plan["queries"])
    return p


def gather(tools: Tools, plan: dict, spec: dict, item: dict, others: list[dict],
           link_cache: Optional[dict] = None, hint: Optional[dict] = None) -> dict:
    text = item_text(spec, item)
    ev = {"demand": {}, "blocks": [], "graph": None, "others": [], "allowed": set(), "used": [], "hint": hint}
    if hint:
        plan = with_hint(plan, hint)
    if "demand" in plan["sources"]:
        for name, (label, v) in labelled_fields(spec, item).items():
            ev["demand"][name] = (label, v)
            ev["allowed"].add(f"demand:{name}")
        ev["used"].append("the demand's own fields")
    if "documents" in plan["sources"]:
        seen, blocks = set(), []
        docs = plan.get("documents") or None
        for q in plan["queries"]:
            query = _fill(q, item, text)
            for b in tools.search(query, 6, docs) or []:
                if b["block_id"] not in seen:
                    seen.add(b["block_id"])
                    blocks.append(b)
        if docs and len(blocks) < 4 and not (hint and hint.get("document")):   # the plan's documents had little: widen to the rest
            # (never when the architect named the document: say it was empty rather than look elsewhere)
            for b in tools.search(_fill(plan["queries"][0], item, text), 6, None) or []:
                if b["block_id"] not in seen:
                    seen.add(b["block_id"])
                    blocks.append(b)
        ev["blocks"] = blocks[:MAX_BLOCKS]
        ev["allowed"] |= {b["block_id"] for b in ev["blocks"]}
        ev["used"].append(("documents: " + ", ".join(docs)) if docs else "the ingested documents")
    if "graph" in plan["sources"]:
        key = item.get("_id")
        lk = link_cache.get(key) if link_cache is not None else None
        if lk is None:
            try:
                lk = tools.link(text) or {}
            except Exception:
                lk = {}
            if link_cache is not None:
                link_cache[key] = lk
        ids = [i for e in lk.get("entities", []) for i in e["ids"]][:6]
        if ids:
            g = tools.graph_facts(ids) or {}
            ev["graph"] = {"names": [n for e in lk["entities"] for n in e["names"]][:8],
                           "facts": g.get("facts", ""), "block_ids": g.get("block_ids", [])}
            extra = tools.blocks_by_ids(g.get("block_ids", [])[:6]) if g.get("block_ids") else []
            known = {b["block_id"] for b in ev["blocks"]}
            for b in extra:
                if b["block_id"] not in known:
                    ev["blocks"].append(b)
            ev["allowed"] |= {b["block_id"] for b in ev["blocks"]}
            ev["used"].append("the graph: " + ", ".join(ev["graph"]["names"][:4]))
    if "other_demands" in plan["sources"]:
        for o in others[:MAX_OTHERS]:
            ev["others"].append({"id": o.get("_id"), "text": item_text(spec, o)[:400]})
            ev["allowed"].add(f"demand:{o.get('_id')}")
        if ev["others"]:
            ev["used"].append("the other demands in the sheet")
    return ev


def render(ev: dict) -> str:
    out = []
    h = ev.get("hint")
    if h:
        out.append("THE ARCHITECT POINTED YOU HERE: " + "; ".join(
            x for x in (f"document {h['document']}" if h.get("document") else "", h.get("where") or "") if x)
            + ". Use what the source blocks below say; if they do not answer it, say so.")
    if ev["demand"]:
        out.append("DEMAND FIELDS:\n" + "\n".join(f"  [demand:{k}] {label}: {v}" for k, (label, v) in ev["demand"].items()))
    if ev["blocks"]:
        out.append("SOURCE BLOCKS:\n" + "\n".join(
            f"  [{b['block_id']}] {(b.get('text') or '')[:BLOCK_CHARS]}" for b in ev["blocks"]))
    if ev["graph"] and ev["graph"]["facts"]:
        out.append(f"GRAPH FACTS (entities: {', '.join(ev['graph']['names'])}):\n" + ev["graph"]["facts"][:3000])
    if ev["others"]:
        out.append("OTHER DEMANDS IN THE SHEET:\n" + "\n".join(f"  [demand:{o['id']}] {o['text']}" for o in ev["others"]))
    return "\n\n".join(out) or "(no evidence found)"
