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
import re
from collections import deque
from typing import Optional

from eawiki.storage import filestore
from eawiki.subjects import llm_json, llm_text

# KB keys, relative to the data root (local ./data, or the GCS bucket in prod).
GRAPH_KEY = "graph/graph.json"
MENU_KEY = "togaf92_metamodel.json"

TEMPLATES = ("neighbors", "path", "impact", "orphans", "aggregate", "filter")


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

    def resolve_all(self, text: str) -> list[str]:
        """Every entity whose name contains the term (plus node_id exacts) — so a name
        that spans several nodes ('Oracle' = the vendor + two Oracle-19c DBs) seeds the
        traversal from all of them, not just one. Used by impact."""
        if not text:
            return []
        t = text.strip().lower()
        hits = [nid for nid, n in self.by_id.items()
                if n.get("name", "").lower() == t or t in n.get("name", "").lower()]
        if t in self.by_id and t not in hits:
            hits.append(t)
        hits.sort(key=lambda nid: len(self.name(nid)))
        return hits or ([self.resolve(text)] if self.resolve(text) else [])


def _menu_types() -> dict:
    txt = filestore().read_text(MENU_KEY)
    return json.loads(txt).get("node_types", {}) if txt else {}


def _load() -> _Graph:
    # Read fresh per call. graph.json is small (~100KB) and only the graph-template queries
    # touch it, so re-reading costs little — and it means a bucket upload is reflected
    # immediately with no restart, so local and prod behave identically.
    txt = filestore().read_text(GRAPH_KEY)
    g = json.loads(txt) if txt else {"nodes": [], "edges": []}
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
    seeds = g.resolve_all(node_id)          # multi-seed: a name may span several nodes
    if not seeds:
        return _result(g, "impact", [], [], [], "", f"Could not find '{node_id}' in the graph.", found=False)
    seen = set(seeds)
    used: list[dict] = []
    frontier = deque([(s, 0) for s in seeds])
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
    affected = [n for n in seen if n not in seeds]
    label = " / ".join(g.name(s) for s in seeds)
    facts = (f"IMPACT — entities connected to {label} within {max_hops} hop(s) "
             f"(direction={direction}): {len(affected)} affected.\n"
             + "\n".join(_edge_line(g, e) for e in used)) if used else \
            f"{label} has no connected entities."
    return _result(g, "impact", list(seeds), seen, used, facts,
                   f"{len(affected)} entit{'y' if len(affected) == 1 else 'ies'} connected to {label} "
                   f"within {max_hops} hop(s)" + (f" (seeded from {len(seeds)} nodes)" if len(seeds) > 1 else "") + ".")


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


def _degree_edges(g: _Graph, nid: str, relation: Optional[str], direction: str) -> list[dict]:
    es: list[dict] = []
    if direction in ("out", "both"):
        es += g.out.get(nid, [])
    if direction in ("in", "both"):
        es += g.inc.get(nid, [])
    return [e for e in es if not relation or e.get("relation") == relation]


def aggregate(g: _Graph, node_type: Optional[str] = None, relation: Optional[str] = None,
              direction: str = "both", entity: Optional[str] = None,
              target_type: Optional[str] = None, top: int = 10) -> dict:
    """Count / rank. With `entity`: how many matching links it has (e.g. 'how many
    capabilities does Finance own'). Without: rank entities by connection count. In both
    cases `relation` and `target_type` (the type of the OTHER endpoint) narrow what counts,
    so 'how many capabilities' only tallies edges whose other end is a capability."""
    def other(e: dict, cur: str) -> str:
        return e["target"] if e["source"] == cur else e["source"]

    def keep(e: dict, cur: str) -> bool:
        return ((not relation or e.get("relation") == relation)
                and (not target_type or g.by_id.get(other(e, cur), {}).get("type") == target_type))

    tt = f" {target_type.replace('_', ' ')}" if target_type else ""
    if entity:
        sid = g.resolve(entity)
        if not sid:
            return _result(g, "aggregate", [], [], [], "", f"Could not find '{entity}'.", found=False)
        pool = []
        if direction in ("out", "both"):
            pool += [(e, e["target"]) for e in g.out.get(sid, []) if keep(e, sid)]
        if direction in ("in", "both"):
            pool += [(e, e["source"]) for e in g.inc.get(sid, []) if keep(e, sid)]
        used = [e for e, _ in pool]
        ids = {sid} | {o for _, o in pool}
        rel = relation or "any"
        facts = (f"{g.name(sid)} has {len(used)} '{rel}'{tt} relationship(s) ({direction}):\n"
                 + "\n".join(_edge_line(g, e) for e in used)) if used else \
                f"{g.name(sid)} has no '{rel}'{tt} relationships ({direction})."
        return _result(g, "aggregate", [sid], ids, used, facts,
                       f"{g.name(sid)}: {len(used)} '{rel}'{tt} link(s).")

    cand = [nid for nid, n in g.by_id.items() if not node_type or n.get("type") == node_type]
    scored = [(nid, [e for e in _degree_edges(g, nid, relation, direction) if keep(e, nid)]) for nid in cand]
    scored = sorted([(nid, es) for nid, es in scored if es], key=lambda s: len(s[1]), reverse=True)[:max(1, top)]
    label = (node_type.replace("_", " ") + " ") if node_type else ""
    rel = f" by '{relation}'" if relation else ""
    facts = (f"{label}entities ranked by{tt} connection count{rel} ({direction}):\n"
             + "\n".join(f"- {g.name(nid)}: {len(es)}" for nid, es in scored)) if scored else \
            f"No {label}entities with matching relationships."
    ids = {nid for nid, _ in scored}
    used = [e for e in g.edges if e["source"] in ids and e["target"] in ids]
    return _result(g, "aggregate", [scored[0][0]] if scored else [], ids, used, facts,
                   f"Top {len(scored)} {label}by{tt} connections{rel}.")


def filter_edges(g: _Graph, source_type: Optional[str] = None, relation: Optional[str] = None,
                 target_type: Optional[str] = None) -> dict:
    """All relationships matching a structural pattern source_type --relation--> target_type
    (any slot may be a wildcard), e.g. 'which applications send data to a data store'."""
    matches = [e for e in g.edges
               if (not relation or e.get("relation") == relation)
               and (not source_type or g.by_id.get(e["source"], {}).get("type") == source_type)
               and (not target_type or g.by_id.get(e["target"], {}).get("type") == target_type)]
    ids = set()
    for e in matches:
        ids.update((e["source"], e["target"]))
    desc = f"{source_type or 'any'} --{relation or 'any'}--> {target_type or 'any'}"
    facts = (f"Relationships matching [{desc}] — {len(matches)}:\n"
             + "\n".join(_edge_line(g, e) for e in matches)) if matches else \
            f"No relationships match [{desc}]."
    return _result(g, "filter", [], ids, matches, facts,
                   f"{len(matches)} relationship(s) matching {desc}.", found=bool(matches))


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
- "impact": what is affected across multiple hops. Slots: a (entity), direction. Use direction "in" for what DEPENDS ON / is affected by X (the right choice for "what breaks if we retire/remove X"); "out" for what X itself depends on; "both" only when the question is genuinely non-directional.
- "orphans": entities of a type that are MISSING a relationship (e.g. "capabilities with no owner"). Slots: node_type, relation, direction (in|out).
- "aggregate": count or rank by number of connections (e.g. "most connected system", "how many capabilities does Finance own"). Slots: a (entity, only when counting ONE entity's links), node_type (to rank within a type), relation, target_type (the type of the things being counted — e.g. for "how many CAPABILITIES does X own", target_type = business_capability), direction.
- "filter": all relationships matching a structural pattern (e.g. "which applications send data to a data store"). Slots: source_type, relation, target_type.
- "none": the question is not a structural graph query (summaries, definitions, free text).

Fill slots using ONLY values from this catalogue (copy names/types/relations verbatim; use null when a slot does not apply):
{_catalog(g)}

Question: {question}

JSON: {{"template": "neighbors|path|impact|orphans|aggregate|filter|none", "a": <entity or null>, "b": <entity or null>, "node_type": <node type or null>, "source_type": <node type or null>, "target_type": <node type or null>, "relation": <relation or null>, "direction": "in|out|both|null"}}"""
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
    types = {n.get("type") for n in g.by_id.values()}
    rels = {e.get("relation") for e in g.edges}

    def ok_type(v):   # a provided type slot must be a real node type
        return v is None or v in types

    def ok_rel(v):    # a provided relation slot must be a real edge relation
        return v is None or v in rels

    if t == "neighbors" and slots.get("a"):
        r = neighbors(g, slots["a"], direction)
    elif t == "path" and slots.get("a") and slots.get("b"):
        r = path(g, slots["a"], slots["b"])
    elif t == "impact" and slots.get("a"):
        r = impact(g, slots["a"], direction)
    elif t == "orphans" and slots.get("node_type") and slots.get("relation"):
        if not (ok_type(slots["node_type"]) and ok_rel(slots["relation"])):
            return None
        r = orphans(g, slots["node_type"], slots["relation"], "out" if direction == "both" else direction)
    elif t == "aggregate" and (slots.get("a") or slots.get("node_type") or slots.get("relation")):
        if not (ok_type(slots.get("node_type")) and ok_type(slots.get("target_type")) and ok_rel(slots.get("relation"))):
            return None
        r = aggregate(g, slots.get("node_type"), slots.get("relation"), direction,
                      slots.get("a"), slots.get("target_type"))
    elif t == "filter" and (slots.get("source_type") or slots.get("relation") or slots.get("target_type")):
        if not (ok_type(slots.get("source_type")) and ok_type(slots.get("target_type")) and ok_rel(slots.get("relation"))):
            return None
        r = filter_edges(g, slots.get("source_type"), slots.get("relation"), slots.get("target_type"))
    else:
        return None
    return r


# --- guarded generated query (the middle tier, for questions no template covers) ------
_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|create|drop|alter|truncate|grant|revoke|import|export|"
    r"merge|upsert|rename|set|remove)\b", re.IGNORECASE)


def _extract_sql(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*", "", t).strip().strip("`").strip()
    m = re.search(r"(?is)\bselect\b.*", t)
    return (m.group(0) if m else t).strip().rstrip(";").strip()


def _guard_sql(sql: str) -> Optional[str]:
    """Read-only guard: single SELECT statement, no write keywords, bounded by LIMIT.
    (The ArcadeDB /query endpoint is read-only too, so this is defense-in-depth.)"""
    if not sql or ";" in sql:                      # one statement only
        return None
    if not re.match(r"(?is)^\s*select\b", sql):    # must be a read
        return None
    if _WRITE_WORDS.search(sql):                   # no mutation verbs anywhere
        return None
    if not re.search(r"(?i)\blimit\b", sql):       # always bound the result size
        sql += " LIMIT 50"
    return sql


def _rows_to_view(g: _Graph, rows: list) -> tuple[list, list]:
    """Best-effort: turn result rows into a render graph. Rows with source/target become
    edges; any entity names/ids found become nodes."""
    ids: set[str] = set()
    edges: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        s = row.get("source") or row.get("src") or row.get("a")
        t = row.get("target") or row.get("dst") or row.get("b")
        if s and t:
            si, ti = g.resolve(str(s)), g.resolve(str(t))
            if si and ti:
                edges.append({"source": si, "target": ti, "relation": str(row.get("relation") or "related")})
                ids.update((si, ti))
                continue
        for v in row.values():
            if isinstance(v, str):
                nid = g.resolve(v)
                if nid:
                    ids.add(nid)
    return [_node_view(g, nid, 0) for nid in ids], edges


def _verify(question: str, sql: str, backend: str, model) -> dict:
    """Back-translation check: describe what the SQL returns, then judge whether that
    matches the question's intent. Catches 'valid but logically wrong' queries."""
    prompt = f"""Check whether a database query correctly answers a question.

Question: {question}

ArcadeDB SQL query (graph of Entity vertices + REL edges; REL.relation holds the relationship name):
{sql}

In ONE sentence, say what rows this query returns, then judge whether that is what the question asks for. Return ONE JSON object:
{{"paraphrase": "<what the query returns, in plain English>", "match": true or false, "reason": "<short why>"}}"""
    try:
        out = llm_json(prompt, backend, model)
        if isinstance(out, dict) and "match" in out:
            return {"paraphrase": out.get("paraphrase", ""), "match": bool(out.get("match")),
                    "reason": out.get("reason", "")}
    except Exception:
        pass
    return {"paraphrase": "", "match": False, "reason": "verification call failed"}


def generate(question: str, backend: str = "cli", model=None, g: Optional[_Graph] = None) -> Optional[dict]:
    """Middle tier: the model WRITES a read-only ArcadeDB query, we guard it, run it, and
    fall back (return None) on any failure. Used only when no template matched. The query
    is back-translation-verified; on mismatch the result is marked unverified (the pipeline
    then abstains from using it as the authoritative answer but still surfaces it)."""
    g = g or _load()
    types = sorted({n.get("type", "") for n in g.by_id.values() if n.get("type")})
    rels = sorted({e.get("relation", "") for e in g.edges if e.get("relation")})
    ex1 = ("SELECT a.name AS source, e.relation AS relation, b.name AS target FROM "
           "(MATCH {type:Entity, where:(name='Payment Gateway'), as:a}.outE('REL'){as:e}"
           ".inV(){as:b} RETURN a, e, b) LIMIT 50")
    ex2 = ("SELECT cap.name AS source FROM (MATCH {type:Entity, as:cap}"
           ".outE('REL'){where:(relation='is_owned_by'), as:e}"
           ".inV(){where:(name='Licensing Department')} RETURN cap) LIMIT 50")
    prompt = f"""Write ONE read-only ArcadeDB SQL query that answers the question over this graph. Output ONLY the SQL — no prose, no backticks.

Schema:
- Vertex Entity(node_id, name, type)
- Edge REL(relation)  from Entity to Entity. There is ONLY ONE edge type, "REL".
  The relationship name (e.g. 'is_owned_by') is a PROPERTY of REL, NOT an edge class.
Valid node types: {', '.join(types)}
Valid relations: {', '.join(rels)}
Entity names — use these EXACT strings in where:(name='...') clauses (do not invent or paraphrase):
{', '.join(sorted(n.get('name', '') for n in g.by_id.values() if n.get('name')))}

Rules:
- SELECT only. No INSERT/UPDATE/DELETE/CREATE/DROP. One statement.
- Traverse with .outE('REL')/.inV()/.bothE('REL') — NEVER .in('is_owned_by') or .out('<relation>'); the relation is filtered as a property: .outE('REL'){{where:(relation='is_owned_by'), as:e}}.
- Wrap the MATCH in SELECT ... FROM ( MATCH ... RETURN ... ).
- When returning relationships, name the columns source, relation, target (entity NAMES).
- Always include LIMIT.

Example — "what does the Payment Gateway connect to":
{ex1}
Example — "which capabilities are owned by the Licensing Department" (relation as a property filter):
{ex2}

Question: {question}
SQL:"""
    try:
        sql = _guard_sql(_extract_sql(llm_text(prompt, backend, model)))
    except Exception:
        return None
    if not sql:
        return None
    try:
        from eawiki.store import ArcadeDBStore
        rows = ArcadeDBStore().query(sql, timeout=6)
    except Exception:
        return None
    if not rows:
        return None
    v = _verify(question, sql, backend, model)       # back-translation verify
    nodes, edges = _rows_to_view(g, rows)
    shown = rows[:40]
    facts = (f"GENERATED QUERY (ArcadeDB SQL, read-only):\n{sql}\n\nRESULTS ({len(rows)}):\n"
             + "\n".join(json.dumps(r, ensure_ascii=False) for r in shown))
    return {"template": "generated", "found": True, "query": sql,
            "summary": f"generated query → {len(rows)} row(s)", "facts": facts,
            "centers": [], "nodes": nodes, "edges": edges, "block_ids": [],
            "verified": v["match"], "verification": v,
            "authoritative": v["match"]}       # unverified → not used as the answer source


def answer(question: str, backend: str = "cli", model=None) -> Optional[dict]:
    """Classify + run in one call. Returns a GraphResult or None (no template applied).
    Direction for impact is decided by the classifier from the prompt's semantics
    ('in' = what depends on X — the right choice for 'what breaks if we retire X')."""
    slots = classify(question, backend, model)
    if not slots:
        return None
    r = run_slots(slots, backend, model)
    if r is not None:
        r["slots"] = {k: slots.get(k) for k in
                      ("template", "a", "b", "node_type", "source_type", "target_type", "relation", "direction")}
    return r
