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
from concurrent.futures import ThreadPoolExecutor
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
            adjudicate=None, extra_pairs=None, apply_llm: bool = True,
            max_adjudications: int = 0, workers: int = 4, overrides: Optional[dict] = None) -> dict:
    """Resolve node mentions into canonical nodes.

    mentions: [{name, type, origin, evidence?, block_id?, ...}] — nodes + endpoints.
    edges:    the raw edges (used for neighbour overlap); names/types as-authored.
    adjudicate: optional callable(pair_a, pair_b) -> bool or (bool, reason). Tier 3.
    extra_pairs: [(a_key, b_key, similarity)] candidates found by meaning (name embeddings),
        which the string tiers cannot see ("Oracle DB" / "Oracle Database"); they join the
        flagged list and go to Tier 3 like any other flagged pair.
    apply_llm: False records what Tier 3 WOULD merge ("would merge") without merging.
    max_adjudications: cap on Tier-3 questions per run (0 = no cap); highest similarity first.
    overrides: {"merge": [[a, b]...], "separate": [[a, b]...]} by name — human decisions that
        always win over the model and the string rules.

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

    # Tier 1b: `element` is the fallback type for "the extractor could not say what this is",
    # so it is not a real type conflict. An `element` entity whose normalized name equals that
    # of exactly ONE typed entity is the same thing seen without its type: merge it into the
    # typed one (typed first, so it stays the root and keeps its type). With two or more typed
    # candidates the name is ambiguous, so it is left alone for a human / Tier 3.
    typed_by_name: dict[str, list] = defaultdict(list)
    for k in keys:
        if k[1] != "element":
            typed_by_name[k[0]].append(k)
    generic_merges: list[dict] = []
    for k in keys:
        if k[1] == "element" and len(typed_by_name.get(k[0], [])) == 1:
            t = typed_by_name[k[0]][0]
            uf.union(t, k)
            generic_merges.append({"a": t[0], "b": k[0], "type": f"{t[1]} <- element",
                                   "tier": "1b", "name_sim": 1.0, "edge_overlap": None,
                                   "decision": "generic-type merge"})

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
    merges: list[dict] = list(generic_merges)
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

    # Candidates found by MEANING (name embeddings): pairs the spelling rules cannot see.
    # `seen_pairs` records every pair the string tiers LOOKED at, including the ones they
    # rejected as too different, so it cannot be used here: only skip a pair already flagged.
    already_flagged = {tuple(sorted((fp["a_key"], fp["b_key"]))) for fp in flagged}
    for a, b, esim in (extra_pairs or []):
        if a not in clusters or b not in clusters:
            continue
        pair = tuple(sorted((a, b)))
        if pair in already_flagged or uf.find(a) == uf.find(b):
            continue
        already_flagged.add(pair)
        flagged.append({"a": canon_name(a), "b": canon_name(b),
                        "type": a[1] if a[1] == b[1] else f"{a[1]} / {b[1]}",
                        "a_key": a, "b_key": b, "name_sim": round(name_sim(a[0], b[0]), 2),
                        "embed_sim": round(float(esim), 3), "edge_overlap": round(overlap(a, b), 2),
                        "reason": "semantically similar name (embedding)"})

    # Human decisions always win. A "merge" joins every entity carrying either name; a
    # "separate" keeps the pair out of every automatic step.
    ov = overrides or {}
    keep_apart = {frozenset((normalize(a), normalize(b))) for a, b in ov.get("separate", [])}
    for a, b in ov.get("merge", []):
        group = sorted((k for k in keys if k[0] in (normalize(a), normalize(b))),
                       key=lambda k: k[1] == "element")      # a typed entity stays the root
        if len(group) > 1:
            for k in group[1:]:
                uf.union(group[0], k)
            merges.append({"a": a, "b": b, "type": "any", "tier": "override", "name_sim": None,
                           "edge_overlap": None, "decision": "override-merge"})
    for fp in flagged:
        if frozenset((fp["a_key"][0], fp["b_key"][0])) in keep_apart:
            fp["decision"] = "override-separate"

    # --- Tier 3: LLM adjudication on the flagged pairs --------------------
    if adjudicate is not None:
        todo = []
        for fp in flagged:
            if fp.get("decision"):
                continue
            if uf.find(fp["a_key"]) == uf.find(fp["b_key"]):
                fp["decision"] = "already merged"
            else:
                todo.append(fp)
        # most promising first: closest by meaning, then by spelling
        todo.sort(key=lambda fp: (-(fp.get("embed_sim") or 0.0), -fp["name_sim"]))
        # The cap bounds NEW model questions only. Pairs that already have a saved decision cost
        # nothing, so they are always included — otherwise every run would re-read the same top
        # N pairs and never reach the rest, and a cap of N would mean "N pairs, ever".
        is_cached = getattr(adjudicate, "is_cached", None)
        if max_adjudications and is_cached:
            known = [fp for fp in todo if is_cached(clusters[fp["a_key"]], clusters[fp["b_key"]])]
            fresh = [fp for fp in todo if fp not in known]
            batch = known + fresh[:max_adjudications]
        else:
            batch = todo[:max_adjudications] if max_adjudications else todo
        chosen = {id(fp) for fp in batch}
        for fp in todo:
            if id(fp) not in chosen:
                fp["decision"] = "not adjudicated (limit)"

        def _decide(fp):
            try:
                r = adjudicate(clusters[fp["a_key"]], clusters[fp["b_key"]])
                same, why = r if isinstance(r, tuple) else (bool(r), "")
                return bool(same), why, None
            except Exception as ex:
                return False, "", f"{type(ex).__name__}: {str(ex)[:80]}"

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            decisions = list(ex.map(_decide, batch))
        for fp, (same, why, err) in zip(batch, decisions):
            if err:
                fp["decision"] = f"adjudication error: {err}"
                continue
            fp["llm_reason"] = why
            if not same:
                fp["decision"] = "separate"
            elif not apply_llm:
                fp["decision"] = "would merge"
            else:
                fp["decision"] = "merge"
                uf.union(fp["a_key"], fp["b_key"])
                merges.append({"a": fp["a"], "b": fp["b"], "type": fp["type"],
                               "tier": "3-llm", "name_sim": fp["name_sim"],
                               "edge_overlap": fp["edge_overlap"], "decision": "llm-merge",
                               "reason": why})
    else:
        for fp in flagged:
            if uf.find(fp["a_key"]) == uf.find(fp["b_key"]):
                fp.setdefault("decision", "already merged")
            else:
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
        # The merged entity's type is decided by its MEMBERS, never by which key the union-find
        # happened to use as the root: `element` means "the extractor could not say", so a typed
        # member always outranks it. Without this, an `element` root silently stripped the real
        # type from every entity it absorbed, and the schema check then demoted their edges.
        weight: dict = defaultdict(int)
        for k in members:
            weight[k[1]] += len(clusters[k]["mentions"]) or 1
        typed = [t for t in weight if t != "element"]
        typ = max(typed, key=lambda t: (weight[t], t)) if typed else "element"
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
            **({"type_conflict": sorted(typed)} if len(typed) > 1 else {}),
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
