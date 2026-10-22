"""Step 7 — Community detection over the reconciled graph.

Groups the Step-4 graph into communities (the functional clusters a landscape page
is written about — e.g. Payments, Licensing). Grouping is driven by the graph's
intrinsic structure: communities come from the edges via **Louvain** (networkx; a
Leiden-family modularity method), and each community is annotated with its dominant
**TOGAF domain** (from the metamodel) for the BDAT coverage view. Edgeless nodes are
kept as singleton communities (coverage answer, not dropped).

System of record = files (`communities.json`); it is also projected into ArcadeDB as
`Community` vertices + `IN_COMMUNITY` membership edges so a global question can traverse
"everything in the Payments community" in one hop.

    python -m eawiki.community                 # detect + write + load into ArcadeDB
    python -m eawiki.community --no-load        # files only
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
from networkx.algorithms.community import louvain_communities

from eawiki.store import ArcadeDBStore

# highest-level business entities make the clearest community label
_ANCHOR_ORDER = ["value_stream", "business_capability", "business_function",
                 "business_service", "product", "process"]


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "community"


def _domain_of(node_type: str, menu: dict) -> str:
    nt = menu.get("node_types", {}).get(node_type)
    return (nt or {}).get("domain", "Other")


def detect(graph: dict, menu: dict) -> list[dict]:
    """Return communities (largest first), each annotated with domain + a label."""
    nodes = {n["node_id"]: n for n in graph["nodes"]}
    G = nx.Graph()
    G.add_nodes_from(nodes)                       # include isolated nodes as singletons
    for e in graph["edges"]:
        s, t = e.get("source"), e.get("target")
        if s in nodes and t in nodes and s != t:
            w = float(e.get("source_count", 1))
            if G.has_edge(s, t):
                G[s][t]["weight"] += w
            else:
                G.add_edge(s, t, weight=w)

    parts = louvain_communities(G, weight="weight", seed=42)
    degree = dict(G.degree())

    communities: list[dict] = []
    for members in sorted(parts, key=len, reverse=True):
        members = list(members)
        types = [nodes[m]["type"] for m in members]
        # label: the highest-level business anchor present, else the hub (max degree)
        label_id = None
        for anchor in _ANCHOR_ORDER:
            cand = [m for m in members if nodes[m]["type"] == anchor]
            if cand:
                label_id = max(cand, key=lambda m: degree.get(m, 0))
                break
        if label_id is None:
            label_id = max(members, key=lambda m: degree.get(m, 0))
        dom = Counter(_domain_of(t, menu) for t in types).most_common(1)[0][0]
        communities.append({
            "name": nodes[label_id]["name"], "dominant_domain": dom,
            "size": len(members),
            "member_ids": sorted(members),
            "member_names": sorted(nodes[m]["name"] for m in members),
        })
    for i, c in enumerate(communities):
        c["community_id"] = f"c{i}"
        c["slug"] = _slug(c["name"])
    return communities


def project(store: ArcadeDBStore, communities: list[dict]) -> None:
    """(Re)create Community vertices + IN_COMMUNITY edges in ArcadeDB."""
    store.command("DROP TYPE IN_COMMUNITY IF EXISTS UNSAFE")
    store.command("DROP TYPE Community IF EXISTS UNSAFE")
    store.command("CREATE VERTEX TYPE Community IF NOT EXISTS")
    store.command("CREATE EDGE TYPE IN_COMMUNITY IF NOT EXISTS")
    store.command("CREATE PROPERTY Community.community_id IF NOT EXISTS STRING")
    store.command("CREATE INDEX IF NOT EXISTS ON Community (community_id) UNIQUE")
    for c in communities:
        store.insert("Community", {
            "community_id": c["community_id"], "name": c["name"],
            "slug": c["slug"], "dominant_domain": c["dominant_domain"], "size": c["size"],
            "summary": c.get("summary", ""),
        })
        for mid in c["member_ids"]:
            try:
                store.add_edge("IN_COMMUNITY", mid, c["community_id"], {},
                               key_from="node_id", from_type="Entity",
                               key_to="community_id", to_type="Community")
            except Exception:
                pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 7 — community detection")
    ap.add_argument("--graph", default="data/graph/graph.json")
    ap.add_argument("--menu", default="data/togaf92_metamodel.json")
    ap.add_argument("--out", default="data/graph/communities.json")
    ap.add_argument("--no-load", dest="load", action="store_false",
                    help="write files only; do not project into ArcadeDB")
    args = ap.parse_args()

    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    menu = json.loads(Path(args.menu).read_text(encoding="utf-8"))
    communities = detect(graph, menu)

    Path(args.out).write_text(json.dumps(
        {"method": "louvain (networkx), domain-annotated",
         "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "count": len(communities), "communities": communities},
        indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"communities: {len(communities)}")
    for c in communities:
        print(f"  {c['community_id']:4s} {c['name']:28s} [{c['dominant_domain']:11s}] "
              f"{c['size']:2d} members")

    if args.load:
        store = ArcadeDBStore()
        project(store, communities)
        print(f"projected {len(communities)} Community vertices + IN_COMMUNITY edges")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
