"""The fixture knowledge base written in the formats the product reads, so the REAL graph code runs on it.

graph/graph.json, pages/*.md, blocks/<doc>.blocks.json and the metamodel are written to a data root and the
file store is pointed at it. `cases.tools.real_tools()` then reads them through the real code: the graph
(`query.graphquery`), the pages (`query.executor`), the question linker (`query.link`, which calls the model),
and the entity resolution. ONLY the passage search is a stand-in (lexical, from tests/kb_fixture.py): the real
one is a vector search over ArcadeDB with an embedding model, which this environment cannot load.
"""
import json
import os
import tempfile
from pathlib import Path

import kb_fixture as kb
from eawiki.cases import namelookup as nl

ROOT = Path(__file__).resolve().parents[1]


def materialize(root: Path) -> None:
    (root / "graph").mkdir(parents=True, exist_ok=True)
    (root / "pages").mkdir(exist_ok=True)
    (root / "blocks").mkdir(exist_ok=True)
    gid = {n["node_id"]: n["slug"] for n in kb.NODES}          # the graph names its entities, not the catalog ids
    nodes = [{"node_id": gid[n["node_id"]], "name": n["name"], "type": n["type"],
              "aliases": list(n["aliases"]) + list(n["ids"]), "evidence": [n["desc"]]} for n in kb.NODES]
    edges = [{"source": gid[a], "target": gid[b], "relation": r, "block_ids": [kb.FIRST_BLOCK[a]]} for a, r, b in kb.EDGES]
    (root / "graph" / "graph.json").write_text(json.dumps({"nodes": nodes, "edges": edges}), encoding="utf-8")
    for slug, md in kb.PAGES.items():
        (root / "pages" / f"{slug}.md").write_text(md, encoding="utf-8")
    for doc in kb.DOCS:
        bl = [{"block_id": b["block_id"], "doc_id": doc, "type": "paragraph", "text": b["text"]} for b in kb.BLOCKS if b["doc_id"] == doc]
        (root / "blocks" / f"{doc}.blocks.json").write_text(json.dumps({"blocks": bl}), encoding="utf-8")
    (root / "togaf92_metamodel.json").write_text((ROOT / "data" / "togaf92_metamodel.json").read_text(encoding="utf-8"), encoding="utf-8")


class LexicalRetriever:
    """The stand-in for the vector store. Everything else the tools do is real."""
    def vector_search(self, q, k=8, docs=None, kinds=None):
        return kb.search(q, k, docs)

    def blocks_by_ids(self, ids):
        return [dict(b) for b in kb.BLOCKS if b["block_id"] in ids]

    def embed_query(self, q):
        raise RuntimeError("no embedding model in this environment")


def real_tools(backend: str = "cli"):
    root = Path(tempfile.mkdtemp(prefix="eawiki_kb_"))
    materialize(root)
    os.environ.update(EAWIKI_DATA=str(root), FILE_BACKEND="local", EAWIKI_API_BACKEND=backend, EAWIKI_CACHE_TTL="0")
    from eawiki.query import graph as qgraph
    from eawiki.storage import filestore
    filestore.cache_clear()
    qgraph._retriever = lambda: LexicalRetriever()
    from eawiki.cases.tools import real_tools as rt
    return rt()
