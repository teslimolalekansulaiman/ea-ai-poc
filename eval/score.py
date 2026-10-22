"""Evaluation harness — precision / recall / F1 of the extracted graph vs a gold set.

Measures how much of the hand-labelled truth (eval/gold.json) the pipeline actually
captured in data/graph/graph.json, for ENTITIES and RELATIONS, with normalization and
alias-awareness (so "Buzz Aldrin" == "Edwin Aldrin"-style variants still match).

    python eval/score.py                 # uses eval/gold.json + data/graph/graph.json

RECALL is the trustworthy number (did we capture the stated facts). PRECISION is scoped
to facts sourced from the gold docs and is a LOWER BOUND — the seed gold is incomplete,
so a graph fact not in the gold isn't necessarily wrong. Extend gold.json to tighten it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def main() -> None:
    gold = json.loads((ROOT / "eval/gold.json").read_text(encoding="utf-8"))
    graph = json.loads((ROOT / "data/graph/graph.json").read_text(encoding="utf-8"))
    gold_docs = set(gold["docs"])

    nodes = graph["nodes"]
    edges = graph["edges"]

    # name/alias -> node_id  (resolve gold names to graph nodes)
    name2id: dict[str, str] = {}
    for n in nodes:
        for nm in [n.get("name", "")] + n.get("aliases", []):
            if nm:
                name2id.setdefault(norm(nm), n["node_id"])
    graph_names = set(name2id)

    def from_gold_docs(block_ids) -> bool:
        return any((b.split(":")[0] in gold_docs) for b in (block_ids or []))

    # ---- ENTITIES ----
    gold_ent = {norm(e["name"]) for e in gold["entities"]}
    ent_tp = len(gold_ent & graph_names)
    ent_fn = len(gold_ent - graph_names)                 # gold entities we missed
    # precision scope: graph nodes sourced from the gold docs
    doc_nodes = [n for n in nodes if from_gold_docs(n.get("block_ids"))]
    ent_fp = sum(1 for n in doc_nodes if norm(n["name"]) not in gold_ent
                 and not (set(map(norm, n.get("aliases", []))) & gold_ent))
    ep, er, ef = prf(ent_tp, ent_fp, ent_fn)
    missed_ent = sorted(e["name"] for e in gold["entities"] if norm(e["name"]) not in graph_names)

    # ---- RELATIONS ----
    edge_keys, edge_pairs, edge_docmask = set(), set(), {}
    for e in edges:
        k = (e["source"], e.get("relation"), e["target"])
        edge_keys.add(k)
        edge_pairs.add((e["source"], e["target"]))
        edge_docmask[(e["source"], e["target"])] = from_gold_docs(e.get("block_ids"))

    rel_tp = rel_tp_any = rel_fn = 0
    missed_rel = []
    for r in gold["relations"]:
        s, t = name2id.get(norm(r["source"])), name2id.get(norm(r["target"]))
        hit_exact = s and t and (s, r["relation"], t) in edge_keys
        hit_any = s and t and (s, t) in edge_pairs
        if hit_exact:
            rel_tp += 1
        if hit_any:
            rel_tp_any += 1
        else:
            rel_fn += 1
            missed_rel.append(f'{r["source"]} --{r["relation"]}--> {r["target"]}')
    # precision scope: graph edges sourced from the gold docs
    gold_pairs = {(name2id.get(norm(r["source"])), name2id.get(norm(r["target"]))) for r in gold["relations"]}
    doc_edges = [e for e in edges if from_gold_docs(e.get("block_ids"))]
    rel_fp = sum(1 for e in doc_edges if (e["source"], e["target"]) not in gold_pairs)
    rp, rr, rf = prf(rel_tp_any, rel_fp, rel_fn)

    # ---- report ----
    print(f"gold docs: {', '.join(sorted(gold_docs))}")
    print(f"graph: {len(nodes)} nodes, {len(edges)} edges\n")
    print("ENTITIES")
    print(f"  recall    {er:.2f}   ({ent_tp}/{ent_tp + ent_fn} gold entities found)")
    print(f"  precision {ep:.2f}   (of {len(doc_nodes)} graph nodes from gold docs; LOWER BOUND — seed gold)")
    print(f"  F1        {ef:.2f}")
    if missed_ent:
        print(f"  missed:   {missed_ent}")
    print("\nRELATIONS  (matched alias-aware; direction required)")
    print(f"  recall (relation-agnostic) {rr:.2f}   ({rel_tp_any}/{rel_tp_any + rel_fn} gold links found)")
    print(f"  recall (exact predicate)   {rel_tp/(rel_tp_any+rel_fn):.2f}   ({rel_tp}/{rel_tp_any + rel_fn} with the labelled relation)")
    print(f"  precision {rp:.2f}   (of {len(doc_edges)} graph edges from gold docs; LOWER BOUND)")
    print(f"  F1        {rf:.2f}")
    if missed_rel:
        print("  missed links:")
        for m in missed_rel:
            print(f"    - {m}")


if __name__ == "__main__":
    sys.exit(main())
