"""The real tools the engine uses: the retriever, the question linker, the graph and the model."""

from __future__ import annotations

from eawiki.cases.gather import Tools


def _graph_nodes(g) -> list[dict]:
    """The graph's entities in the shape the name lookup reads: name, type, other names, catalog ids, page slug."""
    from eawiki.cases import namelookup as nl
    from eawiki.pages import _slug
    out = []
    for nid, n in g.by_id.items():
        names = [a for a in (n.get("aliases") or []) if a and a != n.get("name")]
        ids = [a for a in names + [n.get("name", "")] if nl.is_id(a)]
        out.append({"node_id": nid, "name": n.get("name", ""), "type": n.get("type", ""),
                    "aliases": [a for a in names if not nl.is_id(a)], "ids": ids, "slug": _slug(n.get("name", ""))})
    return out


def real_tools() -> Tools:
    from eawiki.query import graph as qgraph
    from eawiki.query import graphquery as gq
    from eawiki.query import link as lk
    from eawiki.storage import filestore
    from eawiki.subjects import llm_json
    from eawiki.cases import namelookup as nl
    import json
    import os
    import time
    from pathlib import Path

    backend = os.environ.get("EAWIKI_API_BACKEND", "openrouter")
    model = os.environ.get("EAWIKI_ASK_MODEL") or None
    r = qgraph._retriever()

    def search(q, k, docs):
        return r.vector_search(q, k=k, docs=docs) if docs else r.vector_search(q, k=k)

    def link(text):
        res = lk.link(text, backend, model, embed=r.embed_query)
        return res

    def graph_facts(ids):
        g = gq._load()
        facts, blocks = [], []
        for nid in ids:
            res = gq.neighbors(g, nid)
            facts.append(res.get("facts", ""))
            blocks += res.get("block_ids", [])
        return {"facts": "\n".join(f for f in facts if f), "block_ids": list(dict.fromkeys(blocks))}

    def doc_ids():
        fs = filestore()
        out = []
        for key in fs.list("blocks", ".blocks.json"):
            out.append(Path(key).name.replace(".blocks.json", ""))
        return sorted(out)

    cache: dict = {"at": 0.0, "nodes": [], "by_id": {}}

    def nodes() -> list[dict]:
        """The graph is re-read at most once a minute: a name lookup runs for every mention of every demand."""
        if time.time() - cache["at"] > 60 or not cache["nodes"]:
            ns = _graph_nodes(gq._load())
            cache.update(at=time.time(), nodes=ns, by_id={n["node_id"]: n for n in ns})
        return cache["nodes"]

    def nearest(mention):
        from eawiki import entity_index
        idx = entity_index.load_index()
        if idx is None:
            return []
        return idx.nearest_nodes(r.embed_query(mention), 6)

    def entities(mention, kinds=None):
        ns = nodes()
        cands = nl.resolve_entities(mention, ns, nearest, k=4, kinds=kinds)
        others = nl.other_kinds(mention, ns, kinds or [])
        for c in cands + others:
            c["slug"] = cache["by_id"][c["id"]]["slug"]
        return {"candidates": cands, "other_kinds": others}

    def page(slug):
        """A wiki page by slug; an item listed only on a catalogue page is read from that page's own section."""
        from eawiki.query import executor as ex
        md = ex._page_text(slug)
        if md:
            return md
        red = ex._redirects().get(slug)
        cat = ex._page_text(red["page"]) if red else None
        return ex._catalogue_excerpt(cat, red["name"]) if cat else None

    def doc_blocks(doc, limit):
        """A short document's passages in reading order: a standard or a glossary is read whole, not searched."""
        raw = filestore().read_text(f"blocks/{Path(doc).name}.blocks.json")
        bl = (json.loads(raw) if raw else {}).get("blocks", [])
        return [{"block_id": b.get("block_id"), "doc_id": doc, "text": b.get("text") or ""} for b in bl
                if b.get("block_id") and (b.get("text") or "").strip() and b.get("type") != "figure"][:limit]

    return Tools(search=search, blocks_by_ids=r.blocks_by_ids, link=link, graph_facts=graph_facts,
                 llm_json=lambda prompt: llm_json(prompt, backend, model), doc_ids=doc_ids,
                 entities=entities, page=page, doc_blocks=doc_blocks)
