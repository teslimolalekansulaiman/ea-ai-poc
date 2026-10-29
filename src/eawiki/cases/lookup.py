"""One lookup of a property, end to end: the six steps of the page finder for every name it starts from.

  1. match each name to the graph's entities (namelookup)         code
  2. ask the page finder about the names step 1 could not settle    model, once per set of names (pagefinder)
  3. check and merge the picks                                      code
  4. read the wiki page of the best candidates                      code (wikiread)
  5. read the graph around them, for the relationships the lookup names   code (graphread)
  6. search the documents with the lookup's own question            code (passages; a vector search in production)

A lookup that starts from no name can ask for one more thing (`pages`): the finder reads the titles and summaries of the wiki's
pages and picks those that could answer the lookup's question, and step 4 reads them. Off unless the lookup says so.

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


def _page_search(lookup: dict, demand_text: str, kb, llm_text, cache: dict) -> dict:
    """The finder over the wiki's pages, asked the lookup's own question; the picked pages are read like any other (step 4).
    Asked once for a question and a demand."""
    key = ("pages", lookup.get("find"), demand_text)
    if key not in cache:
        found = pagefinder.find_pages(str(lookup.get("find") or ""), demand_text, kb.wiki_entries(), llm_text)
        read = wikiread.read({"pages": found["picks"]}, kb.page, deep=f"{lookup.get('find') or ''} {demand_text[:600]}") if found["picks"] else {"pages": [], "status": {}}
        status = read["status"].get("pages", {})
        cache[key] = {**found, "read": read["pages"],
                      "picked": [{"name": c["name"], "slug": c["slug"], "state": status.get(c["id"], "not read")} for c in found["picks"]]}
    return cache[key]


def run(lookup: dict, mentions: list, demand_text: str, kb, search_fn: Callable, llm_text: Optional[Callable],
        cache: dict, group: str = "systems", strict: bool = False, expand_fn: Optional[Callable] = None, lanes_k: Optional[dict] = None) -> dict:
    """mentions: the names to look up, [None] for the demand as a whole, or [] when the demand names nothing of this kind (nothing is searched). Returns
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
    psg = passages.read(lookup, mentions, demand_text, search_fn, cands, strict, expand_fn, lanes_k)
    # a question that starts from no name may also be answered by a wiki page: the finder reads their titles and summaries
    page_search = _page_search(lookup, demand_text, kb, llm_text, cache) if (kb and lookup.get("pages")) else None
    pages = list(wiki["pages"])
    if page_search:
        by_slug = {p["slug"]: p for p in pages}
        by_slug.update({p["slug"]: p for p in page_search["read"]})        # a page read for the question has its body as well: it wins
        pages = list(by_slug.values())
    items = []
    for it in psg["items"]:
        m = it["mention"]
        items.append({**it, "candidates": cands.get(m, []), "other_kinds": other.get(m, []), "ambiguous": ambiguous.get(m, False),
                      "finder": finder_state.get(m, ""), "wiki": wiki["status"].get(m, {}), "graph_status": graph["status"].get(m, {})})
    return {"items": items, "wiki": pages, "graph": graph, "blocks": psg["blocks"], "notes": notes, "page_search": page_search}
