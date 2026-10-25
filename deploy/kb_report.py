#!/usr/bin/env python3
"""Summarise the published knowledge base: sizes, edgeless entities, suspected duplicates.

    python3 deploy/kb_report.py [bucket]        # bucket defaults to $KB_BUCKET

Reads graph/graph.json, isolated_nodes.json, merge_report.json (and communities.json if it
exists) with `gcloud storage cp`, so it needs only gcloud and the standard library. Set
KB_REPORT_DIR to a local folder to read the files from disk instead.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter


def fetch(bucket, name):
    local = os.environ.get("KB_REPORT_DIR")
    if local:
        p = os.path.join(local, name)
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    tmp = os.path.join(tempfile.mkdtemp(), name)
    r = subprocess.run(["gcloud", "storage", "cp", f"gs://{bucket}/graph/{name}", tmp],
                       capture_output=True, text=True)
    return json.load(open(tmp, encoding="utf-8")) if r.returncode == 0 else None


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def main():
    bucket = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("KB_BUCKET", "")
    if not bucket and not os.environ.get("KB_REPORT_DIR"):
        sys.exit("usage: kb_report.py <bucket>   (or set KB_BUCKET)")
    graph = fetch(bucket, "graph.json") or {"nodes": [], "edges": []}
    isolated = fetch(bucket, "isolated_nodes.json") or []
    merge = fetch(bucket, "merge_report.json") or {"merges": [], "flagged": []}
    comms = fetch(bucket, "communities.json")

    nodes, edges = graph.get("nodes", []), graph.get("edges", [])
    print(f"entities {len(nodes)}   relationships {len(edges)}   edgeless {len(isolated)}   "
          f"communities {'(none: communities.json missing)' if comms is None else len(comms.get('communities', []))}")
    print("entity types:", dict(Counter(n.get("type") for n in nodes).most_common(8)))
    rel = Counter(e.get("relation") for e in edges)
    print("relationship types:", dict(rel.most_common(8)))
    generic = rel.get("associated_with", 0)
    print(f"generic 'associated_with' relationships: {generic} of {len(edges)}"
          f" ({100 * generic // max(1, len(edges))}%)")
    print(f"entities typed as the generic 'element': "
          f"{sum(1 for n in nodes if n.get('type') == 'element')} of {len(nodes)}")

    flagged = merge.get("flagged", [])
    in_flag = {norm(x) for f in flagged for x in (f.get("a"), f.get("b"))}
    iso_names = [n.get("name") for n in isolated]
    hit = [x for x in iso_names if norm(x) in in_flag]
    print(f"\nmerges {len(merge.get('merges', []))}   flagged near-duplicate pairs {len(flagged)}")
    print(f"edgeless entities that are one side of a flagged pair: {len(hit)} of {len(isolated)}")
    both_edgeless = sum(1 for f in flagged
                        if norm(f.get("a")) in {norm(x) for x in iso_names}
                        and norm(f.get("b")) in {norm(x) for x in iso_names})
    print(f"flagged pairs where BOTH sides are edgeless: {both_edgeless}")
    tally = Counter(str(f.get("decision", "")).split(":")[0] for f in flagged)
    print(f"merge mode: {merge.get('mode', '?')}   model/override decisions: {dict(tally)}")
    proposals = [f for f in flagged if f.get("decision") in ("would merge", "merge")]
    for f in proposals[:15]:
        print(f"  {f['decision']:>11}: {f['a']}  =  {f['b']}   ({f.get('llm_reason', '')})")
    typed = Counter(n.get("type") for n in isolated)
    print("edgeless by type:", dict(typed.most_common(6)))
    print("\nsample edgeless 'element' entities:",
          [n.get("name") for n in isolated if n.get("type") == "element"][:12])


if __name__ == "__main__":
    main()
