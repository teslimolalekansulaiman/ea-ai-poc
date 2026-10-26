"""Step 4 — Reconcile the extracted facts into one clean graph.

Merges the three fact files (tables / prose / figures) into a single deduplicated
graph. Node identity is resolved by `dedupe.resolve` (deterministic Tiers 1-2 +
optional Tier-3 LLM on flagged pairs); edges are then rewritten onto the resolved
node ids, deduplicated, and re-validated against the schema triples. Edgeless nodes
are KEPT (a node is a page and a real entity) and reported separately.

Outputs:
  data/graph/graph.json           — {nodes, edges} the canonical deduped graph
  data/graph/isolated_nodes.json  — resolved nodes with no edges (kept, for review)
  data/graph/merge_report.json    — every auto-merge + every flagged pair + decisions

    python -m eawiki.reconcile --menu data/togaf92_metamodel.json            # deterministic
    python -m eawiki.reconcile --menu data/togaf92_metamodel.json --adjudicate cli  # + Tier 3
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from eawiki import dedupe
from eawiki.dedupe import normalize
from eawiki.blocks import content_hash
from eawiki.subjects import effective_model, llm_text, _extract_json, llm_json
from eawiki.tables import _allowed_triple, _validate_llm_facts


_DEMOTED = re.compile(r"^demoted from '([^']+)'")


def restore_relation(menu: dict, e: dict, source_type: str, target_type: str) -> str:
    """The relation to use for an edge once its endpoints are resolved. An edge the extractor
    typed (say `is_deployed_on`) was demoted to `associated_with` only because an endpoint was
    still the generic `element`. If the resolved endpoint types now make the extractor's own
    relation lawful, give it back. Nothing is inferred: it is what the extractor said."""
    rel = e.get("relation")
    m = _DEMOTED.match(e.get("note") or "")
    if rel == "associated_with" and m and _allowed_triple(menu, source_type, m.group(1), target_type):
        return m.group(1)
    return rel


# ---------------------------------------------------------------------------
# load the three fact files into a common shape, stamping origin by source
# ---------------------------------------------------------------------------
def _load(path: Path, origin: str, node_key: str) -> tuple[list[dict], list[dict]]:
    if not path.exists():
        return [], []
    d = json.loads(path.read_text(encoding="utf-8"))
    nodes, edges = [], []
    for n in d.get(node_key, []):
        nodes.append({"name": n.get("name"), "type": n.get("type"),
                      "evidence": n.get("evidence", ""), "block_id": n.get("block_id"),
                      "origin": origin})
    for e in d.get("edges", []):
        e = dict(e)
        e["origin"] = origin
        edges.append(e)
    return nodes, edges


def load_all(graph_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    n1, e1 = _load(graph_dir / "facts_1b.json", "1b-table", "subjects")
    n3, e3 = _load(graph_dir / "facts_3a.json", "3a-text", "nodes")
    nf, ef = _load(graph_dir / "facts_figures.json", "figure-vision", "nodes")
    attrs = []
    f1b = graph_dir / "facts_1b.json"
    if f1b.exists():
        attrs = json.loads(f1b.read_text(encoding="utf-8")).get("attributes", [])
    return (n1 + n3 + nf), (e1 + e3 + ef), attrs


# ---------------------------------------------------------------------------
# Tier-3 adjudicator (LLM) — closure over the raw edges, as a readable context
# ---------------------------------------------------------------------------
def make_adjudicator(edges: list[dict], backend: str, model: Optional[str],
                     cache_dir: Optional[Path] = None):
    """The Tier-3 question: are these two the same real-world entity? Returns (same, reason).
    Answers are cached by the full prompt + backend + model, so an unchanged pair is never
    asked twice; a call that gives no usable answer raises (and is not cached), so the pair is
    retried on the next run instead of being recorded as "different"."""
    edges_by_key = defaultdict(list)
    for e in edges:
        sk = (normalize(e.get("source", "")), e.get("source_type") or "element")
        tk = (normalize(e.get("target", "")), e.get("target_type") or "element")
        desc = f'{e.get("source")} --{e.get("relation")}--> {e.get("target")}'
        edges_by_key[sk].append(desc)
        edges_by_key[tk].append(desc)

    def _prompt_and_file(ca: dict, cb: dict):
        a_desc = dedupe._describe(ca, edges_by_key, None)
        b_desc = dedupe._describe(cb, edges_by_key, None)
        prompt = dedupe.adjudication_prompt(a_desc, b_desc)
        cf = None
        if cache_dir is not None:
            cf = Path(cache_dir) / f"{content_hash(prompt, backend, effective_model(model))}.json"
        return prompt, cf

    def is_cached(ca: dict, cb: dict) -> bool:
        """True when this pair already has a saved decision (so asking costs nothing)."""
        _, cf = _prompt_and_file(ca, cb)
        return cf is not None and cf.exists()

    def adjudicate(ca: dict, cb: dict):
        prompt, cf = _prompt_and_file(ca, cb)
        if cf is not None and cf.exists():
            try:
                d = json.loads(cf.read_text(encoding="utf-8"))
                return bool(d["same"]), d.get("reason", "")
            except Exception:
                pass
        out = llm_json(prompt, backend, model)
        if not isinstance(out, dict) or "same" not in out:
            raise RuntimeError("no usable decision from the model")
        same, why = out.get("same") is True, str(out.get("reason", ""))[:200]
        if cf is not None:
            cf.parent.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps({"same": same, "reason": why}, ensure_ascii=False),
                          encoding="utf-8")
        return same, why

    adjudicate.is_cached = is_cached
    return adjudicate


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Step 4 — reconcile facts into one clean graph")
    ap.add_argument("--graph-dir", default="data/graph")
    ap.add_argument("--blocks", dest="blocks_dir", default="data/blocks",
                    help="source blocks, used to resolve each fact's doc `kind`")
    ap.add_argument("--menu", default="data/togaf92_metamodel.json")
    ap.add_argument("--out", default="data/graph/graph.json")
    ap.add_argument("--adjudicate", choices=["none", "cli", "sdk", "openai", "openrouter", "pulse"],
                    default="none",
                    help="Tier-3 LLM adjudication of flagged pairs (default none = deterministic)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--semantic", action="store_true",
                    help="also propose duplicate candidates by meaning (name embeddings)")
    ap.add_argument("--sim-threshold", type=float, default=0.85,
                    help="cosine similarity at/above which two names become a candidate pair")
    ap.add_argument("--top-k", type=int, default=3, help="max semantic partners per entity")
    ap.add_argument("--merge-mode", choices=["report", "apply"],
                    default=os.environ.get("EAWIKI_MERGE_MODE", "report"),
                    help="report: record what the model WOULD merge; apply: merge it")
    ap.add_argument("--max-pairs", type=int, default=300,
                    help="cap on Tier-3 questions per run (closest pairs first; 0 = no cap)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    gdir = Path(args.graph_dir)
    menu = json.loads(Path(args.menu).read_text(encoding="utf-8"))
    nodes_in, edges_in, attrs = load_all(gdir)

    # block_id -> doc `kind`, so each resolved node/edge records which document
    # class(es) it came from (architecture / motivation / governance / reference).
    kind_by_block: dict[str, str] = {}
    for fp in glob.glob(f"{args.blocks_dir}/*.blocks.json"):
        for b in json.loads(Path(fp).read_text(encoding="utf-8")).get("blocks", []):
            kind_by_block[b["block_id"]] = b.get("kind", "architecture")

    def kinds_for(block_ids) -> list[str]:
        return sorted({kind_by_block.get(b, "architecture") for b in (block_ids or [])}) or ["architecture"]

    # mentions = explicit nodes + every edge endpoint (so endpoints get resolved too)
    mentions = list(nodes_in)
    for e in edges_in:
        if e.get("source"):
            mentions.append({"name": e["source"], "type": e.get("source_type"),
                             "evidence": e.get("evidence", ""), "block_id": e.get("block_id"),
                             "origin": e.get("origin")})
        if e.get("target"):
            mentions.append({"name": e["target"], "type": e.get("target_type"),
                             "evidence": e.get("evidence", ""), "block_id": e.get("block_id"),
                             "origin": e.get("origin")})

    adjudicate = None
    if args.adjudicate != "none":
        adjudicate = make_adjudicator(edges_in, args.adjudicate, args.model, gdir / "merge_cache")

    # Candidates by meaning. Best effort: if the embedder is unavailable the step still runs
    # on the string rules alone, and says so.
    extra_pairs = []
    if args.semantic and adjudicate is not None:
        try:
            from eawiki import semantic
            from eawiki.embed import get_embedder
            keys = sorted({(normalize(m["name"]), m.get("type") or "element")
                           for m in mentions if m.get("name") and normalize(m["name"])})
            vecs = semantic.embed_names([k[0] for k in keys],
                                        get_embedder("openai", None, 0, 1), gdir / "name_embed_cache")
            extra_pairs = semantic.similar_pairs(keys, vecs, args.sim_threshold, args.top_k)
            print(f"semantic: {len(keys)} names embedded, {len(extra_pairs)} candidate pairs "
                  f"(cosine >= {args.sim_threshold})")
        except Exception as e:
            print(f"semantic: skipped ({type(e).__name__}: {str(e)[:100]})")

    overrides = {}
    ov_path = gdir.parent / "merge_overrides.json"
    if ov_path.exists():
        overrides = json.loads(ov_path.read_text(encoding="utf-8"))

    res = dedupe.resolve(mentions, edges_in, adjudicate=adjudicate, extra_pairs=extra_pairs,
                         apply_llm=(args.merge_mode == "apply"), max_adjudications=args.max_pairs,
                         workers=args.workers, overrides=overrides)
    nodes = res["nodes"]
    for n in nodes:                           # which doc class(es) evidence this node
        n["kinds"] = kinds_for(n.get("block_ids"))
    alias = res["alias"]                      # (normkey, type) -> node_id
    by_id = {n["node_id"]: n for n in nodes}

    def nid_of(name, typ):
        return alias.get((normalize(name or ""), typ or "element"))

    # --- rewrite edges onto resolved node ids, then dedupe ----------------
    merged: dict[tuple, dict] = {}
    restored = 0
    for e in edges_in:
        sid = nid_of(e.get("source"), e.get("source_type"))
        tid = nid_of(e.get("target"), e.get("target_type"))
        if not sid or not tid or sid == tid:
            continue  # drop unresolved endpoints and self-loops
        rel = restore_relation(menu, e, by_id[sid]["type"], by_id[tid]["type"])
        if rel != e.get("relation"):
            restored += 1
        acc = e.get("access_type") or ""
        k = (sid, rel, tid, acc)
        rec = merged.get(k)
        if rec is None:
            rec = merged[k] = {
                "source": sid, "source_type": by_id[sid]["type"],
                "relation": rel,
                "target": tid, "target_type": by_id[tid]["type"],
                **({"access_type": acc} if acc else {}),
                "origins": set(), "block_ids": set(), "evidence": [],
            }
        if e.get("origin"):
            rec["origins"].add(e["origin"])
        if e.get("block_id"):
            rec["block_ids"].add(e["block_id"])
        if e.get("evidence") and len(rec["evidence"]) < 3:
            rec["evidence"].append(e["evidence"])

    edges = []
    for rec in merged.values():
        rec["origins"] = sorted(rec["origins"])
        rec["block_ids"] = sorted(rec["block_ids"])
        rec["source_count"] = len(rec["origins"])  # cross-source corroboration
        rec["kinds"] = kinds_for(rec["block_ids"])
        edges.append(rec)

    # --- re-validate the merged edges against the schema triples ----------
    _validate_llm_facts(menu, nodes, edges)

    # --- attach 1b attributes to resolved nodes (best effort) -------------
    for a in attrs:
        sub = a.get("subject")
        if not sub:
            continue
        key_norm = normalize(sub)
        for n in nodes:
            if normalize(n["name"]) == key_norm:
                n.setdefault("attributes", []).append(
                    {"name": a.get("name", ""), "value": a.get("value", ""),
                     "block_id": a.get("block_id")})
                break

    # --- isolated (edgeless) nodes are KEPT, and reported -----------------
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    isolated = [n for n in nodes if n["node_id"] not in connected]

    gpath = Path(args.out)
    gpath.parent.mkdir(parents=True, exist_ok=True)
    gpath.write_text(json.dumps({"nodes": nodes, "edges": edges}, indent=2, ensure_ascii=False),
                     encoding="utf-8")
    (gdir / "isolated_nodes.json").write_text(
        json.dumps(isolated, indent=2, ensure_ascii=False), encoding="utf-8")
    # strip the internal *_key tuples (not JSON-friendly / internal) from the report
    flagged_clean = [{k: v for k, v in fp.items() if k not in ("a_key", "b_key")}
                     for fp in res["flagged"]]
    (gdir / "merge_report.json").write_text(
        json.dumps({"mode": args.merge_mode if adjudicate else "deterministic",
                    "semantic_pairs": len(extra_pairs),
                    "merges": res["merges"], "flagged": flagged_clean}, indent=2,
                   ensure_ascii=False), encoding="utf-8")

    # --- summary ----------------------------------------------------------
    demoted = sum(1 for e in edges if e.get("validation") == "demoted")
    multi = sum(1 for e in edges if e["source_count"] > 1)
    print(f"input : {len(nodes_in)} node mentions + {len(edges_in)} edges "
          f"(from 1b + 3a + figures)")
    print(f"nodes : {len(nodes)} resolved  ({len(mentions)} mentions collapsed)")
    print(f"        merges: {len(res['merges'])} auto/llm   flagged: {len(flagged_clean)}   "
          f"isolated: {len(isolated)}")
    if adjudicate is not None:
        from collections import Counter
        tally = Counter(f["decision"].split(":")[0] for f in flagged_clean)
        print(f"        model decisions ({args.merge_mode}): {dict(tally)}")
    print(f"edges : {len(edges)} unique  (from {len(edges_in)})   "
          f"multi-source: {multi}   demoted->associated_with: {demoted}   restored: {restored}")
    print(f"-> {gpath}")
    print(f"-> {gdir/'isolated_nodes.json'}   -> {gdir/'merge_report.json'}")


if __name__ == "__main__":
    main()
