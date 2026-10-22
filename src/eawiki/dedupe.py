"""Node identity resolution for Step 4 (used by reconcile.py).

Given a pool of node *mentions* (every node and every edge endpoint from the 1b,
3a and figure fact files, each with a `type` and provenance), collapse them into
canonical nodes. The method is the agreed hybrid — deterministic tiers shrink the
problem to a certain core plus a tiny uncertain remainder, and the LLM resolves
only that remainder:

  Tier 1  deterministic   normalize(name)+type -> exact group, auto-merged (~90%)
  Tier 2a deterministic   same-type fuzzy (token Dice) + EDGE-OVERLAP adjudication
                          - high name-sim AND shared neighbour  -> auto-merge
                          - otherwise                            -> flag for Tier 3
  Tier 2b deterministic   same-type pairs that SHARE A NEIGHBOUR but DON'T string
                          match (semantic aliases like K8S-PROD / Kubernetes
                          Production) -> flag for Tier 3 (string logic can't see them)
  Tier 3  LLM (optional)  decide only the flagged pairs, given each node's type,
                          evidence and edges. Scoped to a handful of pairs, never N^2.

Type is always part of the key / gate, so same-name different-type nodes (the
`SMS Gateway` app vs the `Replace SMS Gateway` work_package) never merge.

Pure functions + a small Union-Find; no third-party deps. The reasoning lives in
`adjudication_prompt()` (the reviewable prompt asset) and is called by reconcile.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

# tunables (conservative: prefer under-merge + flag over silent over-merge)
SIM_AUTO = 0.90   # name similarity at/above which a shared-neighbour pair auto-merges
SIM_FLAG = 0.74   # name similarity at/above which a same-type pair is flagged for Tier 3
OVERLAP_FLAG = 0.34  # neighbour-overlap (Jaccard) at/above which a non-string pair is flagged


# ---------------------------------------------------------------------------
# normalization + similarity
# ---------------------------------------------------------------------------
def normalize(name: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace. The Tier-1 identity key."""
    s = (name or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(name: str) -> set[str]:
    return set(normalize(name).split())


def name_sim(a: str, b: str) -> float:
    """Token Dice coefficient in [0,1] — order-independent, good for label variants."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return 2 * inter / (len(ta) + len(tb))


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------
class _UF:
    def __init__(self, items):
        self.p = {x: x for x in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------
def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "node"


def resolve(mentions: list[dict], edges: list[dict],
            adjudicate=None) -> dict:
    """Resolve node mentions into canonical nodes.

    mentions: [{name, type, origin, evidence?, block_id?, ...}] — nodes + endpoints.
    edges:    the raw edges (used for neighbour overlap); names/types as-authored.
    adjudicate: optional callable(pair_a, pair_b) -> bool (True = same). Tier 3.

    Returns {nodes, alias (normkey->node_id), merges[], flagged[]}.
    """
    # --- Tier 1: exact group by (normalized name, type) -------------------
    def key(name, typ):
        return (normalize(name), typ or "element")

    clusters: dict[tuple, dict] = {}   # key -> cluster record
    for m in mentions:
        k = key(m.get("name"), m.get("type"))
        c = clusters.get(k)
        if c is None:
            c = clusters[k] = {"key": k, "type": k[1], "names": [], "mentions": []}
        if m.get("name"):
            c["names"].append(m["name"])
        c["mentions"].append(m)

    keys = list(clusters)
    uf = _UF(keys)

    # neighbour sets on Tier-1 clusters: (relation, other_key) touching a cluster
    neigh: dict[tuple, set] = defaultdict(set)
    for e in edges:
        sk = key(e.get("source"), e.get("source_type"))
        tk = key(e.get("target"), e.get("target_type"))
        if sk in clusters and tk in clusters:
            neigh[sk].add((e.get("relation"), tk))
            neigh[tk].add((e.get("relation"), sk))

    def overlap(a, b) -> float:
        na, nb = neigh.get(a, set()), neigh.get(b, set())
        if not na and not nb:
            return 0.0
        # compare neighbours up to the a/b identity (a neighbour that is the other
        # node doesn't count as shared structure)
        na2 = {(r, (a if n == b else n)) for (r, n) in na}
        nb2 = {(r, (b if n == a else n)) for (r, n) in nb}
        inter = len(na2 & nb2)
        union = len(na2 | nb2)
        return inter / union if union else 0.0

    flagged: list[dict] = []
    merges: list[dict] = []
    seen_pairs: set = set()

    def canon_name(k):
        names = clusters[k]["names"] or [k[0]]
        # most frequent; tie-break on longest (more specific label)
        best = max(set(names), key=lambda n: (names.count(n), len(n)))
        return best

    # --- candidate pairs, grouped by type (blocking) ----------------------
    by_type: dict[str, list] = defaultdict(list)
    for k in keys:
        by_type[k[1]].append(k)

    # token index per type for string-candidate blocking
    for typ, ks in by_type.items():
        tok_index: dict[str, list] = defaultdict(list)
        for k in ks:
            for t in _tokens(k[0]):
                tok_index[t].append(k)

        # Tier 2a: string-similar same-type pairs
        for t, group in tok_index.items():
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    pair = tuple(sorted((a, b)))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    sim = name_sim(a[0], b[0])
                    if sim < SIM_FLAG:
                        continue
                    ov = overlap(a, b)
                    if sim >= SIM_AUTO and ov > 0:
                        uf.union(a, b)
                        merges.append({"a": canon_name(a), "b": canon_name(b), "type": typ,
                                       "tier": "2a", "name_sim": round(sim, 2),
                                       "edge_overlap": round(ov, 2), "decision": "auto-merge"})
                    else:
                        flagged.append({"a": canon_name(a), "b": canon_name(b), "type": typ,
                                        "a_key": a, "b_key": b,
                                        "name_sim": round(sim, 2), "edge_overlap": round(ov, 2),
                                        "reason": "string-similar, needs adjudication"})

        # Tier 2b: same-type pairs that SHARE A NEIGHBOUR but aren't string-similar
        nbr_index: dict[tuple, list] = defaultdict(list)
        for k in ks:
            for rn in neigh.get(k, set()):
                nbr_index[rn].append(k)
        for rn, group in nbr_index.items():
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    pair = tuple(sorted((a, b)))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    ov = overlap(a, b)
                    if ov >= OVERLAP_FLAG:
                        flagged.append({"a": canon_name(a), "b": canon_name(b), "type": typ,
                                        "a_key": a, "b_key": b,
                                        "name_sim": round(name_sim(a[0], b[0]), 2),
                                        "edge_overlap": round(ov, 2),
                                        "reason": "shares a neighbour (possible semantic alias)"})

    # Tier 2c: identical normalized NAME across DIFFERENT types -> flag.
    # Tier-2a/2b block candidates by type, so a node the passes typed
    # inconsistently (e.g. "SMS Gateway" as application vs technology component)
    # is never compared and silently splits. We flag such pairs — never
    # auto-merge, because a same-named app and tech node can be intentional; the
    # type choice is a real modelling decision for Tier 3 / a human.
    by_name: dict[str, list] = defaultdict(list)
    for k in keys:
        by_name[k[0]].append(k)
    for nm, group in by_name.items():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if a[1] == b[1]:
                    continue  # same type already handled by 2a
                pair = tuple(sorted((a, b)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                flagged.append({"a": canon_name(a), "b": canon_name(b),
                                "type": f"{a[1]} / {b[1]}", "a_key": a, "b_key": b,
                                "name_sim": 1.0, "edge_overlap": round(overlap(a, b), 2),
                                "reason": "identical name, conflicting type (pass disagreement)"})

    # --- Tier 3: LLM adjudication on the flagged pairs --------------------
    if adjudicate is not None:
        for fp in flagged:
            a, b = fp["a_key"], fp["b_key"]
            if uf.find(a) == uf.find(b):
                fp["decision"] = "already merged"
                continue
            try:
                same = adjudicate(clusters[a], clusters[b])
            except Exception as ex:
                fp["decision"] = f"adjudication error: {type(ex).__name__}"
                continue
            fp["decision"] = "merge" if same else "separate"
            if same:
                uf.union(a, b)
                merges.append({"a": fp["a"], "b": fp["b"], "type": fp["type"],
                               "tier": "3-llm", "name_sim": fp["name_sim"],
                               "edge_overlap": fp["edge_overlap"], "decision": "llm-merge"})
    else:
        for fp in flagged:
            fp.setdefault("decision", "flagged (no adjudicator)")

    # --- build canonical nodes from the Union-Find clusters ---------------
    groups: dict[tuple, list] = defaultdict(list)
    for k in keys:
        groups[uf.find(k)].append(k)

    nodes: list[dict] = []
    alias: dict[tuple, str] = {}
    used_ids: set = set()
    for root, members in groups.items():
        # canonical name = most frequent across all merged members
        allnames = [n for k in members for n in (clusters[k]["names"] or [k[0]])]
        cname = max(set(allnames), key=lambda n: (allnames.count(n), len(n))) if allnames else root[0]
        typ = root[1]
        nid = _slug(cname)
        base, i = nid, 2
        while nid in used_ids:
            nid = f"{base}-{i}"; i += 1
        used_ids.add(nid)

        origins, bids, evid, mem_names = set(), set(), [], set()
        for k in members:
            alias[k] = nid
            for m in clusters[k]["mentions"]:
                if m.get("origin"):
                    origins.add(m["origin"])
                if m.get("block_id"):
                    bids.add(m["block_id"])
                if m.get("evidence") and len(evid) < 3:
                    evid.append(m["evidence"])
                if m.get("name"):
                    mem_names.add(m["name"])
        nodes.append({
            "node_id": nid, "name": cname, "type": typ,
            "aliases": sorted(n for n in mem_names if n != cname),
            "origins": sorted(origins), "block_ids": sorted(bids),
            "evidence": evid,
        })

    return {"nodes": nodes, "alias": alias, "merges": merges, "flagged": flagged}


# ---------------------------------------------------------------------------
# Tier-3 prompt asset (the reasoning the LLM applies to a flagged pair)
# ---------------------------------------------------------------------------
def _describe(cluster: dict, edges_by_key, alias_name) -> str:
    k = cluster["key"]
    lines = [f'name: "{cluster["names"][0] if cluster["names"] else k[0]}"  (type: {k[1]})']
    ev = next((m.get("evidence") for m in cluster["mentions"] if m.get("evidence")), "")
    if ev:
        lines.append(f'evidence: "{ev[:200]}"')
    es = edges_by_key.get(k, [])
    if es:
        lines.append("edges:")
        for e in es[:8]:
            lines.append(f'  - {e}')
    else:
        lines.append("edges: (none)")
    return "\n".join(lines)


def adjudication_prompt(a_desc: str, b_desc: str) -> str:
    return f"""You decide whether two enterprise-architecture nodes are the SAME real-world entity or two DIFFERENT entities. Output ONE JSON object and nothing else.

They are only the SAME if they denote the identical thing (the same application, component, team, location, etc.) — a name variant, abbreviation, or synonym. They are DIFFERENT if one is a project/change about the other, a part of it, or merely related. When unsure, answer different.

Node A:
{a_desc}

Node B:
{b_desc}

Return: {{"same": true|false, "reason": "<one short sentence>"}}"""
