"""Retrieval over the ArcadeDB projection: vector search + graph traversal.

The query is embedded with the SAME backend/model/dim as the index (read from
embeddings_meta.json) — a query embedded by a different model than the index is
meaningless, so this is load-bearing. Retrieval returns small blocks; `expand()`
does the small->big step (pull a block's neighbours) for the answer context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from eawiki import embed as embmod
from eawiki.store import ArcadeDBStore


class Retriever:
    def __init__(self, store: Optional[ArcadeDBStore] = None,
                 meta_path: str = "data/graph/embeddings_meta.json"):
        from eawiki.storage import filestore, rel_key
        self.store = store or ArcadeDBStore()
        txt = filestore().read_text(rel_key(meta_path))
        if txt is None:
            raise FileNotFoundError(f"embeddings meta not found: {meta_path}")
        meta = json.loads(txt)
        self.backend = meta.get("backend", "hash")
        self.model = meta.get("model")
        self.dim = int(meta.get("dim", 384))
        # MUST match the index's embedder (hash ignores model; st/pulse use it)
        model = None if self.backend == "hash" else self.model
        self._embedder = embmod.get_embedder(self.backend, model, self.dim, 32)

    # --- vector side -----------------------------------------------------
    def embed_query(self, q: str) -> list[float]:
        return [float(x) for x in self._embedder.encode([q])[0]]

    def vector_search(self, q: str, k: int = 8,
                      kinds: Optional[list[str]] = None,
                      docs: Optional[list[str]] = None) -> list[dict]:
        """k nearest blocks to the question, nearest first. If `kinds` is given,
        restrict to those document classes (e.g. ['architecture']) — over-fetch
        then filter, so a governance block isn't returned as an architecture fact."""
        # `docs` restricts to named documents (a use-case property says where to look). The index
        # cannot filter, so over-fetch much more and keep only those documents' blocks.
        fetch = k * 25 if docs else (k * 4 if kinds else k)
        rows = self.store.vector_search(self.embed_query(q), k=fetch)
        want = {d.lower() for d in docs} if docs else None
        out = []
        for r in rows:
            if kinds and r.get("kind", "architecture") not in kinds:
                continue
            if want and str(r.get("doc_id", "")).lower() not in want:
                continue
            dist = r.get("$distance", r.get("distance"))
            out.append({"block_id": r.get("block_id"), "doc_id": r.get("doc_id"),
                        "kind": r.get("kind", "architecture"),
                        "section": r.get("section"), "btype": r.get("btype"),
                        "text": r.get("text", ""), "distance": dist})
            if len(out) >= k:
                break
        return out

    def expand(self, block_id: str, window: int = 1) -> list[dict]:
        """Small->big: the block's immediate neighbours in the same doc (by ordinal)."""
        base = self.store.query(
            "SELECT doc_id, ordinal FROM Block WHERE block_id = :b LIMIT 1",
            params={"b": block_id})
        if not base:
            return []
        doc, ordn = base[0]["doc_id"], base[0].get("ordinal", 0)
        rows = self.store.query(
            "SELECT block_id, btype, section, text, ordinal FROM Block "
            "WHERE doc_id = :d AND ordinal >= :lo AND ordinal <= :hi ORDER BY ordinal",
            params={"d": doc, "lo": ordn - window, "hi": ordn + window})
        return rows or []

    # --- graph side ------------------------------------------------------
    def find_entities(self, text: str, limit: int = 5) -> list[dict]:
        """Entities whose name matches the text (for graph-routed questions)."""
        rows = self.store.query(
            "SELECT node_id, name, type FROM Entity WHERE name.toLowerCase() LIKE :p LIMIT :l",
            params={"p": f"%{text.lower()}%", "l": limit})
        return rows or []

    def entities_in_question(self, question: str, limit: int = 5) -> list[dict]:
        """Entities whose NAME appears in the question (reverse match) — the right
        anchor for a graph question like 'who owns the Payment Gateway?'. Works
        without embeddings, so graph answers are correct even before Pulse."""
        q = (question or "").lower()
        rows = self.store.query("SELECT node_id, name, type FROM Entity")
        hits = [r for r in (rows or []) if r.get("name") and r["name"].lower() in q]
        # longer names first (more specific match wins)
        hits.sort(key=lambda r: len(r["name"]), reverse=True)
        return hits[:limit]

    def blocks_by_ids(self, block_ids: list[str]) -> list[dict]:
        """Fetch block text/section for a set of block_ids (graph-route evidence)."""
        if not block_ids:
            return []
        rows = self.store.query(
            "SELECT block_id, btype, section, text FROM Block WHERE block_id IN :ids",
            params={"ids": list(block_ids)})
        return rows or []

    def subgraph(self, node_id: str) -> dict:
        """Outgoing + incoming typed relationships of an entity (one hop)."""
        out = self.store.query(
            "SELECT e.relation AS relation, dst.name AS target, dst.type AS target_type "
            "FROM (MATCH {type:Entity, where:(node_id=:id)}.outE('REL'){as:e}.inV(){as:dst} "
            "RETURN e, dst)", params={"id": node_id})
        inc = self.store.query(
            "SELECT e.relation AS relation, src.name AS source, src.type AS source_type "
            "FROM (MATCH {type:Entity, where:(node_id=:id)}.inE('REL'){as:e}.outV(){as:src} "
            "RETURN e, src)", params={"id": node_id})
        cites = self.store.query(
            "SELECT out('CITES').block_id AS blocks FROM Entity WHERE node_id = :id",
            params={"id": node_id})
        return {"node_id": node_id, "out": out or [], "in": inc or [],
                "blocks": (cites[0]["blocks"] if cites else [])}
