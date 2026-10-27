"""One lookup of a property, end to end: the six steps of the page finder for every name it starts from.

  1. match each name to the graph's entities (namelookup)         code
  2. ask the page finder about the names step 1 could not settle    model, once per set of names (pagefinder)
  3. check and merge the picks                                      code
  4. read the wiki page of the best candidates                      code (wikiread)
  5. read the graph around them, for the relationships the lookup names   code (graphread)
  6. search the documents with the lookup's own question            code (passages; a vector search in production)

What comes back is one record the answer step reads: per name, its candidates (and how each was found), what its wiki page
says, what the graph links it to, which passages are its entry, which only mention it, and where nothing was found. Every
absence is stated with its reason: a step that could not run is never reported as "nothing found".

`kb` supplies what the steps read: entities() (graph entities as namelookup wants them), graph() (a graphquery._Graph),
page(slug), wiki_entries() (the finder's list). Pure otherwise: the model and the search are passed in.
"""

from __future__ import annotations

from typing import Callable, Optional

from eawiki.cases import graphread, namelookup as nl, pagefinder, passages, wikiread

KIND_FAMILY = {"application": "app", "data": "data", "technology": "tech", "security": "security", "role": "role"}


def kinds_of(lookup: dict) -> Optional[list]:
    return [KIND_FAMILY[t] for t in lookup.get("types") or [] if t in KIND_FAMILY] or None


def _finder(kb, names: list[str], group: str, llm_text, cache: dict) -> dict:
    """Step 2 for the names step 1 left unsettled; the answer is kept for the demand, so a name asked about by several
    lookups costs one question."""
    key = ("finder", group, tuple(sorted(names)))
    if key not in cache:
        index = pagefinder.build_index(kb.entities(), kb.wiki_entries())
        cache[key] = pagefinder.find([{"text": n, "group": group} for n in names], index, llm_text)
    return cache[key]


def run(lookup: dict, mentions: list, demand_text: str, kb, search_fn: Callable, llm_text: Optional[Callable],
        cache: dict, group: str = "systems", strict: bool = False) -> dict:
    """mentions: the names to look up, or [None] for the demand as a whole. Returns
    {'items': [...], 'wiki': [...], 'graph': {...}, 'blocks': [...], 'notes': [...]}."""
    kinds = kinds_of(lookup)
    named = [m for m in mentions if m]
    nodes = kb.entities() if (kb and named and lookup.get("match") == "name") else []
    step1, other, ambiguous = {}, {}, {}
    for m in named:
        step1[m] = nl.resolve_entities(m, nodes, kinds=kinds) if nodes else []
        other[m] = nl.other_kinds(m, nodes, kinds or []) if nodes else []
    notes = []
    # 2-3: what no word settled goes to the page finder; a pick joins the candidates, never as a strong match
    unsettled = [m for m in named if nodes and not any(c["strong"] for c in step1[m])]
    cands = {m: list(step1[m]) for m in named}
    finder_state = {}
    if unsettled:
        res = _finder(kb, unsettled, group, llm_text, cache)
        for m in unsettled:
            if m in res["unread"]:
                finder_state[m] = "unread"
                continue
            merged = pagefinder.merge(step1[m], res["picks"].get(m, []), kinds)
            cands[m] = merged["candidates"]
            other[m] = other[m] + [o for o in merged["other_kinds"] if o["id"] not in {x["id"] for x in other[m]}]
            finder_state[m] = "picked" if res["picks"].get(m) else "none"
    for m in named:
        ambiguous[m] = nl.ambiguous(cands[m])
    # 4: wiki
    wiki = wikiread.read({m: cands[m] for m in named}, kb.page) if (kb and named and nodes) else {"pages": [], "status": {}}
    # 5: graph
    graph = graphread.read({m: cands[m] for m in named}, lookup.get("relations") or [], kb.graph()) if (kb and named and nodes and lookup.get("relations")) else \
        {"skipped": "", "status": {}, "facts": {}, "more": {}, "block_ids": []}
    # 6: passages
    psg = passages.read(lookup, mentions or [None], demand_text, search_fn, cands, strict)
    items = []
    for it in psg["items"]:
        m = it["mention"]
        items.append({**it, "candidates": cands.get(m, []), "other_kinds": other.get(m, []), "ambiguous": ambiguous.get(m, False),
                      "finder": finder_state.get(m, ""), "wiki": wiki["status"].get(m, {}), "graph_status": graph["status"].get(m, {})})
    return {"items": items, "wiki": wiki["pages"], "graph": graph, "blocks": psg["blocks"], "notes": notes}
