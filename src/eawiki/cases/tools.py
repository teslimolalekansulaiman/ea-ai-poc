"""The real tools the engine uses: the retriever, the question linker, the graph and the model."""

from __future__ import annotations

from eawiki.cases.gather import Tools


def real_tools() -> Tools:
    from eawiki.query import graph as qgraph
    from eawiki.query import graphquery as gq
    from eawiki.query import link as lk
    from eawiki.storage import filestore
    from eawiki.subjects import llm_json
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

    return Tools(search=search, blocks_by_ids=r.blocks_by_ids, link=link, graph_facts=graph_facts,
                 llm_json=lambda prompt: llm_json(prompt, backend, model), doc_ids=doc_ids)
