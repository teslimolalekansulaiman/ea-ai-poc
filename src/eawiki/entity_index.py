"""Entity and relationship index — the vectors that let a question find the graph's own words.

A question is worded by a person ("Oracle Database"); the graph is worded by the documents
("Oracle DB"). String matching cannot bridge that, and merging cannot either (a user can phrase a
question in a way no merge predicted). So the FINAL graph (after reconcile) is embedded: one vector
per entity and one per relationship, each from a short text that carries the name, the type, the
other names it is known by and what it is linked to. At question time the closest ones shortlist
the candidates a model then chooses among (eawiki.query.link); the vector only PROPOSES, as in
`semantic`, because a vector cannot tell "Endpoint detection" from "Network detection".

Runs after `embed` (it reuses that step's embedder, so a question embeds the same way as a block)
and before `load`. Vectors are cached on disk by embedding model + text, so a re-run embeds only the
entities whose text changed.

    python -m eawiki.entity_index
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

import numpy as np

INDEX_KEY = "graph/entity_index.npz"
META_KEY = "graph/entity_index_meta.json"
CACHE_FILE = "entity_index_vectors.npz"        # under graph/name_embed_cache (synced with the caches)


def _words(rel: str) -> str:
    return (rel or "associated_with").replace("_", " ")


def entity_text(node: dict, neighbours: list[str]) -> str:
    parts = [f"{node.get('name', '')} ({(node.get('type') or 'element').replace('_', ' ')})."]
    aliases = [a for a in (node.get("aliases") or []) if a and a != node.get("name")][:6]
    if aliases:
        parts.append("Also called: " + "; ".join(aliases) + ".")
    ev = next((e for e in (node.get("evidence") or []) if e), "")
    if ev:
        parts.append(str(ev)[:200])
    if neighbours:
        parts.append("Linked to: " + "; ".join(neighbours[:6]) + ".")
    return " ".join(parts)


def name_text(node: dict) -> str:
    """Just what the entity is called (name, other names, type): a short question such as
    "Oracle Database" must not be diluted by the long list of things the entity is linked to."""
    aliases = [a for a in (node.get("aliases") or []) if a and a != node.get("name")][:6]
    return "; ".join([node.get("name", "")] + aliases) + f" ({(node.get('type') or 'element').replace('_', ' ')})"


def edge_text(e: dict, names: dict) -> str:
    ev = e.get("evidence") or []
    ev = ev[0] if ev else ""
    return (f"{names.get(e['source'], e['source'])} {_words(e.get('relation'))} "
            f"{names.get(e['target'], e['target'])}. {str(ev)[:150]}").strip()


def texts_for(graph: dict) -> tuple[list[dict], list[str], list[dict], list[str]]:
    """(nodes, node texts, edges, edge texts) for a graph.json."""
    nodes = [n for n in graph.get("nodes", []) if n.get("node_id")]
    names = {n["node_id"]: n.get("name", n["node_id"]) for n in nodes}
    edges = [e for e in graph.get("edges", []) if e.get("source") in names and e.get("target") in names]
    nbr: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        nbr[e["source"]].append(f"{_words(e.get('relation'))} {names[e['target']]}")
        nbr[e["target"]].append(f"{names[e['source']]} {_words(e.get('relation'))} it")
    return (nodes, [entity_text(n, nbr[n["node_id"]]) for n in nodes],
            edges, [edge_text(e, names) for e in edges])


def _key(model: str, text: str) -> str:
    return f"{model}|{hashlib.sha1(text.encode('utf-8')).hexdigest()[:20]}"


def embed_cached(texts: list[str], embedder, cache_path: Path) -> np.ndarray:
    """One unit-length vector per text, embedding only what the cache does not hold."""
    from eawiki import semantic
    cache = semantic._load(cache_path)
    model = getattr(embedder, "model", "?")
    keys = [_key(model, t) for t in texts]
    missing = sorted({(k, t) for k, t in zip(keys, texts) if k not in cache})
    if missing:
        vecs = embedder.encode([t for _, t in missing])
        for (k, _), v in zip(missing, vecs):
            cache[k] = np.asarray(v, dtype=np.float32)
        semantic._save(cache_path, cache)
    out = np.stack([cache[k] for k in keys]).astype(np.float32) if keys else np.zeros((0, 1), np.float32)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(norms == 0, 1.0, norms)


class Index:
    """The loaded index: shortlist the nodes and edges closest to a question vector."""

    def __init__(self, node_ids, node_vecs, name_vecs, edge_keys, edge_vecs, model=""):
        self.node_ids = list(node_ids)
        self.node_vecs = node_vecs.astype(np.float32)        # name + links + evidence
        self.name_vecs = name_vecs.astype(np.float32)        # name + other names + type only
        self.edge_keys = list(edge_keys)               # "source\trelation\ttarget"
        self.edge_vecs = edge_vecs.astype(np.float32)
        self.model = model

    def nearest_nodes(self, qvec, k: int = 25) -> list[tuple[str, float]]:
        if not len(self.node_ids):
            return []
        q = np.asarray(qvec, dtype=np.float32)
        sims = np.maximum(self.node_vecs @ q, self.name_vecs @ q)     # a hit on either reading counts
        top = np.argsort(-sims)[:k]
        return [(self.node_ids[i], float(sims[i])) for i in top]

    def nearest_edges(self, qvec, k: int = 10) -> list[tuple[tuple, float]]:
        if not len(self.edge_keys):
            return []
        sims = self.edge_vecs @ np.asarray(qvec, dtype=np.float32)
        top = np.argsort(-sims)[:k]
        return [(tuple(self.edge_keys[i].split("\t")), float(sims[i])) for i in top]


def build_index(graph: dict, embedder, cache_path: Path) -> Index:
    nodes, ntexts, edges, etexts = texts_for(graph)
    nv = embed_cached(ntexts, embedder, cache_path)
    nm = embed_cached([name_text(n) for n in nodes], embedder, cache_path)
    ev = embed_cached(etexts, embedder, cache_path)
    return Index([n["node_id"] for n in nodes], nv, nm,
                 [f"{e['source']}\t{e.get('relation', 'associated_with')}\t{e['target']}" for e in edges],
                 ev, getattr(embedder, "model", ""))


def save_index(idx: Index, out: Path, meta: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, node_ids=np.array(idx.node_ids), node_vecs=idx.node_vecs.astype(np.float16),
                        name_vecs=idx.name_vecs.astype(np.float16), edge_keys=np.array(idx.edge_keys), edge_vecs=idx.edge_vecs.astype(np.float16))
    meta.write_text(json.dumps({"model": idx.model, "nodes": len(idx.node_ids),
                                "edges": len(idx.edge_keys),
                                "dim": int(idx.node_vecs.shape[1]) if len(idx.node_ids) else 0}),
                    encoding="utf-8")


_loaded: dict = {"stamp": None, "index": None}


def load_index() -> Optional[Index]:
    """The published index, or None when the KB has none yet (an older ingest). Re-read only when
    its small meta file changes, so a question does not download the vectors each time."""
    from eawiki.storage import filestore
    fs = filestore()
    stamp = fs.read_text(META_KEY)
    if not stamp:
        return None
    if _loaded["stamp"] == stamp and _loaded["index"] is not None:
        return _loaded["index"]
    raw = fs.read_bytes(INDEX_KEY)
    if not raw:
        return None
    z = np.load(io.BytesIO(raw), allow_pickle=False)
    idx = Index(z["node_ids"], z["node_vecs"], z["name_vecs"], z["edge_keys"], z["edge_vecs"],
                json.loads(stamp).get("model", ""))
    _loaded.update(stamp=stamp, index=idx)
    return idx


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the entity + relationship vector index")
    ap.add_argument("--graph", default="data/graph/graph.json")
    ap.add_argument("--meta", default="data/graph/embeddings_meta.json",
                    help="the block index's embedder settings; the same embedder is used here")
    ap.add_argument("--out", default="data/graph/entity_index.npz")
    ap.add_argument("--out-meta", default="data/graph/entity_index_meta.json")
    ap.add_argument("--cache", default="data/graph/name_embed_cache")
    args = ap.parse_args()

    from eawiki import embed as embmod
    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    emeta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    # Batch size 1: some embeddings routes fold a multi-text batch into one vector.
    embedder = embmod.get_embedder(emeta.get("backend", "openai"), emeta.get("model"),
                                   int(emeta.get("dim", 0)), 1)
    cache_path = Path(args.cache) / CACHE_FILE
    before = len(_cached_keys(cache_path))
    idx = build_index(graph, embedder, cache_path)
    after = len(_cached_keys(cache_path))
    save_index(idx, Path(args.out), Path(args.out_meta))
    print(f"entity index: {len(idx.node_ids)} entities, {len(idx.edge_keys)} relationships "
          f"(model {idx.model})")
    print(f"cache: reused {2 * len(idx.node_ids) + len(idx.edge_keys) - (after - before)}   "
          f"embedded {after - before}")


def _cached_keys(path: Path) -> set:
    from eawiki import semantic
    return set(semantic._load(path))


if __name__ == "__main__":
    main()
