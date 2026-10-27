"""Step 5 of the page finder: read the graph around each candidate, for the relationships the lookup asks for. Code only.

The owner of a use case says, per lookup, which relationships matter and in which direction ("sends_data_to",
both ways; "is_deployed_on", incoming). Only those are read, one hop from each candidate that is an entity of
the graph. A lookup that names no relationships reads nothing here, and says so: reading every relationship of
every candidate would bury the few that answer the question.

What comes back are facts ("Peoplex HR System --sends_data_to--> HR & Payroll Portal"), the entity at the other
end of each, and the passages the edge was extracted from (block ids). A fact is evidence that two things are
linked. Whether the link makes the other end impacted, a duplicate or an owner is for the answer step to say.

Pure: the graph (a query.graphquery._Graph, or anything with by_id, out, inc and same_name) is passed in.
"""

from __future__ import annotations

MAX_PER_MENTION = 3         # candidates per mention whose neighbourhood is read, best first
MAX_FACTS = 10              # facts kept per candidate
MAX_TOTAL = 30              # facts kept per property


def _edges(g, nid: str, direction: str):
    if direction in ("out", "both"):
        for e in g.out.get(nid, []):
            yield e, e["target"], "out"
    if direction in ("in", "both"):
        for e in g.inc.get(nid, []):
            yield e, e["source"], "in"


def _fact(g, e: dict, other: str, direction: str, seed: str) -> dict:
    a, b = g.by_id[e["source"]], g.by_id[e["target"]]
    o = g.by_id[other]
    return {"text": f"{a.get('name', e['source'])} --{e.get('relation')}--> {b.get('name', e['target'])}",
            "relation": e.get("relation"), "direction": direction,
            "other": {"id": other, "name": o.get("name", other), "type": o.get("type", "")},
            "block_ids": list(e.get("block_ids") or [])}


def read(by_mention: dict, relations: list[dict], g, per_mention: int = MAX_PER_MENTION, max_facts: int = MAX_FACTS,
         max_total: int = MAX_TOTAL) -> dict:
    """by_mention: {mention: [candidate, ...]} best first (a candidate: id, name, graph: bool).
    relations: [{'relation', 'direction': 'out'|'in'|'both'}] from the lookup.
    Returns {'skipped': reason or '', 'status': {mention: {candidate id: state}}, 'facts': {candidate id: [fact]},
             'more': {candidate id: facts not shown}, 'block_ids': [...]}.
    state: 'read' | 'none found' (read, nothing of those relationships) | 'no entity' (a page only, nothing in the graph)
           | 'not read' (over a limit) | 'not asked' (the lookup names no relationships)."""
    out = {"skipped": "", "status": {}, "facts": {}, "more": {}, "block_ids": []}
    if not relations:
        out["skipped"] = "this lookup names no graph relationships to read"
        out["status"] = {m: {c["id"]: "not asked" for c in cs} for m, cs in by_mention.items()}
        return out
    total = 0
    blocks: list = []
    for mention, cands in by_mention.items():
        out["status"][mention] = {}
        n_read = 0                                                # a page-only candidate takes no place: nothing of it is read here
        for c in cands:
            cid = c["id"]
            if cid in out["facts"]:                               # already read for another mention
                out["status"][mention][cid] = "read" if out["facts"][cid] else "none found"
                continue
            if not c.get("graph", True) or cid not in g.by_id:
                out["status"][mention][cid] = "no entity"
                continue
            if n_read >= per_mention or total >= max_total:
                out["status"][mention][cid] = "not read"
                continue
            n_read += 1
            facts, seen = [], set()
            for spec in relations:
                rows = []
                for seed in g.same_name(cid):                     # one thing recorded under several nodes is one thing
                    for e, other, d in _edges(g, seed, spec["direction"]):
                        if e.get("relation") == spec["relation"] and (e["source"], e.get("relation"), e["target"]) not in seen:
                            seen.add((e["source"], e.get("relation"), e["target"]))
                            rows.append(_fact(g, e, other, d, seed))
                facts += sorted(rows, key=lambda f: f["other"]["name"].casefold())
            shown = facts[:min(max_facts, max_total - total)]
            out["facts"][cid] = shown
            out["more"][cid] = len(facts) - len(shown)
            total += len(shown)
            blocks += [b for f in shown for b in f["block_ids"]]
            out["status"][mention][cid] = "read" if shown else "none found"
    out["block_ids"] = list(dict.fromkeys(blocks))
    return out
