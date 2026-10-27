"""The real tools the engine uses: the retriever, the question linker, the graph and the model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from eawiki.cases.gather import Tools


def graph_entities(g) -> list[dict]:
    """The graph's entities in the shape the matcher reads (see namelookup): name, type, other names, catalog IDs
    and the slug of the entity's wiki page. `g` is a query.graphquery._Graph."""
    from eawiki.cases import namelookup as nl
    from eawiki.pages import _slug
    out = []
    for nid, n in g.by_id.items():
        others = [a for a in (n.get("aliases") or []) if a and a != n.get("name")]
        out.append({"node_id": nid, "name": n.get("name", ""), "type": n.get("type", ""),
                    "aliases": [a for a in others if not nl.is_id(a)],
                    "ids": [a for a in others + [n.get("name", "")] if nl.is_id(a)],
                    "slug": _slug(n.get("name", ""))})
    return out


def wiki_page_from(fs, slug: str) -> Optional[str]:
    """A wiki page by slug. An item listed only on a catalogue page has no page of its own: it is read as its own
    section of that page (the page_redirects.json map says which)."""
    name = Path(slug).name
    md = fs.read_text(f"pages/{name}.md")
    if md:
        return md
    raw = fs.read_text("graph/page_redirects.json")
    red = (json.loads(raw) if raw else {}).get(name)
    cat = fs.read_text(f"pages/{red['page']}.md") if red else None
    if not cat:
        return None
    sec = next((x for x in cat.split("\n## ")[1:] if x.splitlines()[0].strip().lower() == red["name"].strip().lower()), None)
    return f"# {red['name']}\n\n" + "\n".join(sec.splitlines()[1:]).strip() if sec else None


def wiki_entries_from(fs) -> list[dict]:
    """The wiki as the page finder's list reads it: one entry per page of its own (catalogue pages left out, they
    are not things) and one per item listed only on a catalogue page."""
    from eawiki.cases import pagefinder as pf
    out = []
    for key in fs.list("pages", ".md"):
        slug = Path(key).stem
        if slug.startswith("landscape-") or slug.startswith("catalogue-"):
            continue
        out.append(pf.page_item(slug, fs.read_text(key) or ""))
    raw = fs.read_text("graph/page_redirects.json")
    for slug in (json.loads(raw) if raw else {}):
        md = wiki_page_from(fs, slug)
        if md:
            out.append(pf.page_item(slug, md))
    return out


class RealKB:
    """What the six steps read, from the knowledge base in the file store. The graph and the page list are re-read at most
    once a minute: a lookup runs for every name of every demand."""

    def __init__(self, fs, load_graph, ttl: float = 60.0):
        self.fs, self._load, self.ttl = fs, load_graph, ttl
        self._box: dict = {}

    def _cached(self, key, make):
        import time
        hit = self._box.get(key)
        if hit is None or time.time() - hit[0] > self.ttl:
            hit = (time.time(), make())
            self._box[key] = hit
        return hit[1]

    def graph(self):
        return self._cached("graph", self._load)

    def entities(self) -> list:
        return self._cached("entities", lambda: graph_entities(self.graph()))

    def wiki_entries(self) -> list:
        return self._cached("wiki", lambda: wiki_entries_from(self.fs))

    def page(self, slug):
        return wiki_page_from(self.fs, slug)


def real_tools() -> Tools:
    from eawiki.query import graph as qgraph
    from eawiki.query import graphquery as gq
    from eawiki.query import link as lk
    from eawiki.storage import filestore
    from eawiki.subjects import llm_json, llm_text
    import os
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

    def read_image(block_id, prompt):
        """A vision model's answer to `prompt` about the image of a figure block; None when the block has no image file."""
        import tempfile
        from eawiki.storage import rel_key
        from eawiki.subjects import llm_vision
        fs = filestore()
        raw = fs.read_text(f"blocks/{block_id.rsplit(':', 1)[0]}.blocks.json")
        block = next((b for b in (json.loads(raw)["blocks"] if raw else []) if b.get("block_id") == block_id), None)
        ip = ((block or {}).get("figure") or {}).get("image_path")
        data = fs.read_bytes(rel_key(ip)) if ip else None
        if not data:
            return None
        with tempfile.NamedTemporaryFile(suffix=Path(ip).suffix or ".png", delete=True) as f:
            f.write(data)
            f.flush()
            return llm_vision(prompt, f.name, backend, None)

    return Tools(search=search, blocks_by_ids=r.blocks_by_ids, link=link, graph_facts=graph_facts,
                 llm_json=lambda prompt: llm_json(prompt, backend, model), doc_ids=doc_ids,
                 llm_text=lambda prompt: llm_text(prompt, backend, model), kb=RealKB(filestore(), gq._load), expand=r.expand, read_image=read_image)
