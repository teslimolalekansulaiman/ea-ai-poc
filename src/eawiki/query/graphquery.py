"""Structured graph queries over the architecture graph (the 'text-to-slots' layer).

The LLM never writes a database query. Instead a small whitelist of hand-written,
parameterized traversals runs over graph.json (the source of truth; ArcadeDB is a
disposable projection of it). A classifier maps a question to ONE template and fills
TYPED slots (entity ids resolved against the graph, node/edge types validated against
the metamodel) — so the only model output is a validated slot-fill, never a query
string. That keeps every safety property of a fixed query (no invalid syntax, no
hallucinated labels, no injection) while covering multi-hop, path and gap questions.

Each template returns one `GraphResult` used three ways from a single computation:
  * `facts`     — text handed to the answer model (grounded GRAPH FACTS)
  * `block_ids` — evidence blocks to cite
  * `nodes/edges` — a render-ready slice for the UI (same shape as /api/map)

Templates: neighbors (1-hop, the default), path (A↔B), impact (transitive), orphans
(entities missing a relation — e.g. capabilities with no owner).
"""

from __future__ import annotations

import json
import os
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Optional

from eawiki.subjects import llm_json

GRAPH = Path(os.environ.get("EAWIKI_GRAPH", "data/graph"))
MENU = Path(os.environ.get("EAWIKI_MENU", "data/togaf92_metamodel.json"))

TEMPLATES = ("neighbors", "path", "impact", "orphans")


# --- graph model ---------------------------------------------------------
class _Graph:
    def __init__(self, nodes: list[dict], edges: list[dict], node_types: dict):
        self.by_id = {n["node_id"]: n for n in nodes}
        self.edges = [e for e in edges if e.get("source") != e.get("target")
                      and e.get("source") in self.by_id and e.get("target") in self.by_id]
        self.node_types = node_types
        self.out: dict[str, list[dict]] = {}
        self.inc: dict[str, list[dict]] = {}
        for e in self.edges:
            self.out.setdefault(e["source"], []).append(e)
            self.inc.setdefault(e["target"], []).append(e)

    def domain(self, nid: str) -> str:
        t = self.by_id.get(nid, {}).get("type", "")
        return (self.node_types.get(t, {}) or {}).get("domain", "Other")

    def name(self, nid: str) -> str:
        return self.by_id.get(nid, {}).get("name", nid)

    def resolve(self, text: str) -> Optional[str]:
        """An entity id for a free-text name: exact (case-insensitive) first, then the
        longest unique-ish substring match."""
        if not text:
            return None
        t = text.strip().lower()
        if t in self.by_id:
            return t
        exact = [nid for nid, n in self.by_id.items() if n.get("name", "").lower() == t]
        if exact:
            return exact[0]
        subs = [(nid, n.get("name", "")) for nid, n in self.by_id.items()
                if t in n.get("name", "").lower() or n.get("name", "").lower() in t]
        subs.sort(key=lambda p: len(p[1]), reverse=True)
        return subs[0][0] if subs else None


@lru_cache(maxsize=1)
def _menu_types() -> dict:
    return json.loads(MENU.read_text(encoding="utf-8")).get("node_types", {}) if MENU.exists() else {}


def _load() -> _Graph:
    g = json.loads((GRAPH / "graph.json").read_text(encoding="utf-8")) if (GRAPH / "graph.json").exists() else {"nodes": [], "edges": []}
    return _Graph(g.get("nodes", []), g.get("edges", []), _menu_types())


# --- result assembly -----------------------------------------------------
def _node_view(g: _Graph, nid: str, member: int) -> dict:
    n = g.by_id.get(nid, {})
    return {"id": nid, "name": n.get("name", nid), "type": n.get("type", "element"),
            "domain": g.domain(nid), "member": member}


def _result(g: _Graph, template: str, centers: list[str], node_ids, used_edges: list[dict],
            facts: str, summary: str, found: bool = True) -> dict:
    ids = list(dict.fromkeys(list(node_ids) + centers))
    cset = set(centers)
    block_ids: list[str] = []
    for e in used_edges:
        block_ids += e.get("block_ids", []) or []
    edges = [{"source": e["source"], "target": e["target"],
              "relation": e.get("relation", "associated_with")} for e in used_edges]
    return {
        "template": template, "found": found, "summary": summary, "facts": facts,
        "centers": centers,
        "nodes": [_node_view(g, nid, 1 if nid in cset else 0) for nid in ids if nid in g.by_id],
        "edges": edges,
        "block_ids": list(dict.fromkeys(block_ids)),
    }


def _edge_line(g: _Graph, e: dict) -> str:
    return f"{g.name(e['source'])} --{e.get('relation')}--> {g.name(e['target'])}"


# --- templates -----------------------------------------------------------
def neighbors(g: _Graph, node_id: str, direction: str = "both") -> dict:
    node_id = g.resolve(node_id) or node_id
    if node_id not in g.by_id:
        return _result(g, "neighbors", [], [], [], "", f"'{node_id}' is not in the graph.", found=False)
    used = []
    if direction in ("out", "both"):
        used += g.out.get(node_id, [])
    if direction in ("in", "both"):
        used += g.inc.get(node_id, [])
    ids = {node_id} | {e["source"] for e in used} | {e["target"] for e in used}
    facts = "\n".join(_edge_line(g, e) for e in used) or "(no relationships)"
    return _result(g, "neighbors", [node_id], ids, used,
                   "GRAPH FACTS (1-hop neighbourhood of " + g.name(node_id) + "):\n" + facts,
                   f"{g.name(node_id)} has {len(used)} direct relationship(s).")


def path(g: _Graph, a: str, b: str, max_hops: int = 6) -> dict:
    sa, sb = g.resolve(a), g.resolve(b)
    if not sa or not sb:
        miss = a if not sa else b
        return _result(g, "path", [x for x in (sa, sb) if x], [], [], "",
                       f"Could not find '{miss}' in the graph.", found=False)
    # BFS over the undirected REL graph; remember the edge used to reach each node.
    prev: dict[str, tuple[str, dict]] = {sa: ("", {})}
    q = deque([(sa, 0)])
    while q:
        cur, d = q.popleft()
        if cur == sb:
            break
        if d >= max_hops:
            continue
        for e in g.out.get(cur, []) + g.inc.get(cur, []):
            nxt = e["target"] if e["source"] == cur else e["source"]
            if nxt not in prev:
                prev[nxt] = (cur, e)
                q.append((nxt, d + 1))
    if sb not in prev:
        return _result(g, "path", [sa, sb], [sa, sb], [], "",
                       f"No path between {g.name(sa)} and {g.name(sb)} within {max_hops} hops.", found=False)
    # backtrack sb -> sa, collecting the edges used and the ordered node sequence
    chain, seq, cur = [], [sb], sb
    while cur != sa:
        p, e = prev[cur]
        chain.append(e)
        seq.append(p)
        cur = p
    chain.reverse()
    seq.reverse()
    arrow = " → ".join(g.name(n) for n in seq)
    facts = f"PATH from {g.name(sa)} to {g.name(sb)} ({len(chain)} hop(s)):\n" + \
            "\n".join(_edge_line(g, e) for e in chain)
    return _result(g, "path", [sa, sb], set(seq), chain, facts,
                   f"{len(chain)}-hop path: {arrow}")


def impact(g: _Graph, node_id: str, direction: str = "both", max_hops: int = 3) -> dict:
    sid = g.resolve(node_id)
    if not sid:
        return _result(g, "impact", [], [], [], "", f"Could not find '{node_id}' in the graph.", found=False)
    seen = {sid}
    used: list[dict] = []
    frontier = deque([(sid, 0)])
    while frontier:
        cur, d = frontier.popleft()
        if d >= max_hops:
            continue
        nbrs = []
        if direction in ("out", "both"):
            nbrs += [(e, e["target"]) for e in g.out.get(cur, [])]
        if direction in ("in", "both"):
            nbrs += [(e, e["source"]) for e in g.inc.get(cur, [])]
        for e, nxt in nbrs:
            if e not in used:
                used.append(e)
            if nxt not in seen:
                seen.add(nxt)
                frontier.append((nxt, d + 1))
    affected = [n for n in seen if n != sid]
    facts = (f"IMPACT — entities connected to {g.name(sid)} within {max_hops} hop(s) "
             f"(direction={direction}): {len(affected)} affected.\n"
             + "\n".join(_edge_line(g, e) for e in used)) if used else \
            f"{g.name(sid)} has no connected entities."
    return _result(g, "impact", [sid], seen, used, facts,
                   f"{len(affected)} entit{'y' if len(affected) == 1 else 'ies'} connected to {g.name(sid)} "
                   f"within {max_hops} hop(s).")


def orphans(g: _Graph, node_type: str, relation: str, direction: str = "out") -> dict:
    hits = []
    for nid, n in g.by_id.items():
        if n.get("type") != node_type:
            continue
        pool = g.out.get(nid, []) if direction == "out" else g.inc.get(nid, [])
        if not any(e.get("relation") == relation for e in pool):
            hits.append(nid)
    hits.sort(key=lambda x: g.name(x).lower())
    pretty = node_type.replace("_", " ")
    facts = (f"{pretty} entities with NO '{relation}' ({direction}) relationship — {len(hits)}:\n"
             + "\n".join(f"- {g.name(h)}" for h in hits)) if hits else \
            f"Every {pretty} has a '{relation}' relationship."
    return _result(g, "orphans", [], hits, [], facts,
                   f"{len(hits)} {pretty} with no '{relation}'.")


# --- classifier (text -> template + typed slots) -------------------------
def _catalog(g: _Graph) -> str:
    names = sorted({n.get("name", "") for n in g.by_id.values() if n.get("name")})
    types = sorted({n.get("type", "") for n in g.by_id.values() if n.get("type")})
    rels = sorted({e.get("relation", "") for e in g.edges if e.get("relation")})
    return (f"ENTITIES: {', '.join(names)}\n\nNODE_TYPES: {', '.join(types)}\n\n"
            f"RELATIONS: {', '.join(rels)}")


def classify(question: str, backend: str = "cli", model=None, g: Optional[_Graph] = None) -> Optional[dict]:
    """Map a question to {template, slots} filled ONLY from the catalog. Returns None
    when no graph template applies (the caller then falls back to normal retrieval)."""
    g = g or _load()
    prompt = f"""You convert an enterprise-architecture question into ONE structured graph query, choosing from a fixed set of templates. Output ONE JSON object, nothing else.

Templates:
- "neighbors": what is directly related to one entity. Slots: a (entity), direction (in|out|both).
- "path": how two entities are connected. Slots: a (entity), b (entity).
- "impact": what is affected by / connected to one entity across multiple hops (e.g. "what breaks if we retire X"). Slots: a (entity), direction (in|out|both).
- "orphans": entities of a type that are MISSING a relationship (e.g. "capabilities with no owner"). Slots: node_type, relation, direction (in|out).
- "none": the question is not a structural graph query (summaries, definitions, free text).

Fill slots using ONLY values from this catalogue (copy names/types/relations verbatim; use null when a slot does not apply):
{_catalog(g)}

Question: {question}

JSON: {{"template": "neighbors|path|impact|orphans|none", "a": <entity name or null>, "b": <entity name or null>, "node_type": <node type or null>, "relation": <relation or null>, "direction": "in|out|both|null"}}"""
    try:
        out = llm_json(prompt, backend, model)
    except Exception:
        return None
    if not isinstance(out, dict) or out.get("template") not in TEMPLATES:
        return None
    return out


def run_slots(slots: dict, backend: str = "cli", model=None) -> Optional[dict]:
    """Validate a slot-fill against the graph/metamodel and run its template."""
    g = _load()
    t = slots.get("template")
    direction = (slots.get("direction") or "both")
    if direction not in ("in", "out", "both"):
        direction = "both"
    if t == "neighbors" and slots.get("a"):
        r = neighbors(g, slots["a"], direction)
    elif t == "path" and slots.get("a") and slots.get("b"):
        r = path(g, slots["a"], slots["b"])
    elif t == "impact" and slots.get("a"):
        r = impact(g, slots["a"], direction if direction != "both" else "both")
    elif t == "orphans" and slots.get("node_type") and slots.get("relation"):
        nt, rel = slots["node_type"], slots["relation"]
        if nt not in {n.get("type") for n in g.by_id.values()}:   # validate against the graph
            return None
        r = orphans(g, nt, rel, "out" if direction == "both" else direction)
    else:
        return None
    return r


def answer(question: str, backend: str = "cli", model=None) -> Optional[dict]:
    """Classify + run in one call. Returns a GraphResult or None (no template applied)."""
    slots = classify(question, backend, model)
    if not slots:
        return None
    r = run_slots(slots, backend, model)
    if r is not None:
        r["slots"] = {k: slots.get(k) for k in ("template", "a", "b", "node_type", "relation", "direction")}
    return r
