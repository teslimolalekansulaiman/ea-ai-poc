"""Step 6 — Load the clean graph + vectors into ArcadeDB (a projection of the files).

Files stay the system of record; this projects them into the store so they're
queryable (graph traversal + vector search in one place). It is **re-runnable**:
with --reset (default) it drops and rebuilds the projection from the files, so the
DB can be dropped and reloaded anytime without losing anything.

Reads:
  data/graph/graph.json            (nodes + edges, from Step 4)
  data/graph/embeddings.jsonl      (block vectors, from Step 5)
  data/graph/embeddings_meta.json  (vector dim + similarity -> sizes the index)

Loads into ArcadeDB (see eawiki/store.py for the model): Entity + REL for the graph,
Block (+ vector index) for retrieval, CITES linking each entity to the blocks that
evidence it (so a vector hit jumps to its entity/page).

    python -m eawiki.load                 # rebuild from files
    python -m eawiki.load --no-reset      # add on top of what's there
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eawiki.store import ArcadeDBStore


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def block_doc(v: dict) -> dict:
    """The Block vertex of one embedded unit. `part` of `parts` says which piece of its block this is (a long table is several windows, a long
    paragraph several chunks), and a table window says which of its rows it holds (`rows_from` to `rows_to` of `rows_total`): a result can
    then be told to be part 2 of 4, and the missing parts fetched."""
    doc = {
        "id": v["id"], "block_id": v["block_id"], "doc_id": v["doc_id"],
        "btype": v.get("type", ""), "ordinal": v.get("ordinal", 0),
        "kind": v.get("kind", "architecture"),
        "section": " / ".join(v.get("section_path", [])),
        "text": v.get("text", ""), "embedding": v.get("embedding", []),
        "part": v.get("part", 1), "parts": v.get("parts", 1),
    }
    for k in ("rows_from", "rows_to", "rows_total"):
        if v.get(k) is not None:
            doc[k] = v[k]
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 6 — load graph + vectors into ArcadeDB")
    ap.add_argument("--graph", default="data/graph/graph.json")
    ap.add_argument("--embeddings", default="data/graph/embeddings.jsonl")
    ap.add_argument("--meta", default="data/graph/embeddings_meta.json")
    ap.add_argument("--no-reset", dest="reset", action="store_false",
                    help="do NOT drop existing types first (default: reset & rebuild)")
    args = ap.parse_args()

    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    vectors = _read_jsonl(Path(args.embeddings))
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8")) if Path(args.meta).exists() else {}
    dim = int(meta.get("dim", 384))
    similarity = {"cosine": "COSINE", "dot": "DOT_PRODUCT", "euclidean": "EUCLIDEAN"}.get(
        str(meta.get("similarity", "cosine")).lower(), "COSINE")

    store = ArcadeDBStore()
    store.ping()
    print(f"connected: {store.base}/{store.db}   vector dim={dim} similarity={similarity}")

    if args.reset:
        store.reset()
        print("reset: dropped Entity/REL/Block/CITES")
    store.create_schema(dim, similarity)

    # --- entities (vertices) --------------------------------------------
    for n in nodes:
        store.insert("Entity", {
            "node_id": n["node_id"], "name": n.get("name", ""), "type": n.get("type", "element"),
            "aliases": n.get("aliases", []), "origins": n.get("origins", []),
            "kinds": n.get("kinds", ["architecture"]),
            "attributes": json.dumps(n.get("attributes", []), ensure_ascii=False),
        })
    print(f"entities: {len(nodes)}")

    # --- blocks + embeddings (vertices) ---------------------------------
    for v in vectors:
        store.insert("Block", block_doc(v))
    print(f"blocks:   {len(vectors)}")

    # --- relationships (edges) ------------------------------------------
    rel_ok = rel_skip = 0
    for e in edges:
        try:
            store.add_edge("REL", e["source"], e["target"], {
                "relation": e.get("relation", "associated_with"),
                "source_count": e.get("source_count", 1),
                "origins": e.get("origins", []), "evidence": e.get("evidence", []),
                "kinds": e.get("kinds", ["architecture"]),
            })
            rel_ok += 1
        except Exception as ex:
            rel_skip += 1
            if rel_skip <= 3:
                print(f"  ! edge {e.get('source')}->{e.get('target')}: {str(ex)[:80]}")
    print(f"edges:    {rel_ok} loaded ({rel_skip} skipped)")

    # --- provenance links: Entity -CITES-> Block ------------------------
    block_ids = {v["block_id"] for v in vectors}
    cite_ok = 0
    for n in nodes:
        for bid in n.get("block_ids", []):
            if bid not in block_ids:
                continue
            try:
                store.add_edge("CITES", n["node_id"], bid, {},
                               key_to="block_id", to_type="Block")
                cite_ok += 1
            except Exception:
                pass
    print(f"cites:    {cite_ok} entity->block links")

    # --- vector index (build after bulk insert) -------------------------
    store.create_vector_index(dim, similarity)
    print("vector index: Block[embedding] created")

    print("done. verify in Studio (http://localhost:2480) or query with vector.neighbors().")


if __name__ == "__main__":
    main()
