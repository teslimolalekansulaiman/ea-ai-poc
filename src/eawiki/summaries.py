"""Step 8 — Community summaries (grounded).

LLM-summarize each community into a short narrative that serves GLOBAL questions
only — it does not feed or constrain the Step-3a subject pages. Each summary is
grounded: it is built from the community's member entities, their internal
relationships, and their source blocks, and is instructed to cite block ids, so it
never floats free of the documents.

Enriches `communities.json` with a `summary` per community and re-projects the
summaries onto the ArcadeDB Community vertices.

    python -m eawiki.summaries --min-size 3 --workers 6
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eawiki import community as comm
from eawiki.blocks import Block, load_blocks
from eawiki.store import ArcadeDBStore
from eawiki.subjects import llm_text


def block_index(in_dir: str) -> dict[str, Block]:
    idx: dict[str, Block] = {}
    for fp in sorted(glob.glob(f"{in_dir}/*.blocks.json")):
        for b in load_blocks(Path(fp)):
            idx[b.block_id] = b
    return idx


def community_context(c: dict, nodes_by_id: dict, edges: list[dict],
                      blocks_by_id: dict[str, Block], max_blocks: int = 12) -> str:
    members = set(c["member_ids"])
    lines = [f"Community: {c['name']}  (dominant domain: {c['dominant_domain']}, "
             f"{c['size']} members)", "", "MEMBERS:"]
    for mid in c["member_ids"]:
        n = nodes_by_id.get(mid)
        if n:
            lines.append(f"  - {n['name']} ({n['type']})")
    internal = [e for e in edges if e.get("source") in members and e.get("target") in members]
    if internal:
        lines.append("")
        lines.append("INTERNAL RELATIONSHIPS:")
        for e in internal[:40]:
            lines.append(f"  {nodes_by_id[e['source']]['name']} --{e['relation']}--> "
                         f"{nodes_by_id[e['target']]['name']}")
    # evidence blocks: dedup across members, cap
    bids: list[str] = []
    for mid in c["member_ids"]:
        for bid in (nodes_by_id.get(mid, {}).get("block_ids", []) or []):
            if bid not in bids:
                bids.append(bid)
    if bids:
        lines.append("")
        lines.append("SOURCE BLOCKS:")
        for bid in bids[:max_blocks]:
            b = blocks_by_id.get(bid)
            if b and (b.text or "").strip():
                lines.append(f"[{bid}] {(b.text or '').strip()[:300]}")
    return "\n".join(lines)


def summarize(c: dict, ctx: str, backend: str, model) -> str:
    prompt = f"""Write a short GROUNDED summary of this community of an enterprise-architecture landscape, for a reader asking a big-picture question. Use ONLY the context. Say what this area is, its key systems/processes, how they connect, and any notable risks. Cite block ids like [03-data:5]. 1-2 short paragraphs. Do not invent facts.

{ctx}

Summary:"""
    return llm_text(prompt, backend, model).strip()


def _report_failures(path: Path, failed: list[dict], total: int) -> None:
    """Record which items failed (visible, inspectable) and stop only if nothing worked."""
    path.write_text(json.dumps(failed, indent=2, ensure_ascii=False), encoding="utf-8")
    if failed:
        print(f"WARNING: {len(failed)} of {total} failed -> {path}", file=sys.stderr)
    if failed and len(failed) == total:
        raise SystemExit(f"{path.stem}: every item failed; first error: {failed[0]['error']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 8 — community summaries")
    ap.add_argument("--communities", default="data/graph/communities.json")
    ap.add_argument("--graph", default="data/graph/graph.json")
    ap.add_argument("--blocks", dest="in_dir", default="data/blocks")
    ap.add_argument("--min-size", type=int, default=3, help="skip communities smaller than this")
    ap.add_argument("--backend", default="cli", help="LLM backend (cli; pulse later)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-load", dest="load", action="store_false")
    args = ap.parse_args()

    data = json.loads(Path(args.communities).read_text(encoding="utf-8"))
    communities = data["communities"]
    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    nodes_by_id = {n["node_id"]: n for n in graph["nodes"]}
    blocks_by_id = block_index(args.in_dir)

    targets = [c for c in communities if c["size"] >= args.min_size]
    print(f"summarizing {len(targets)} / {len(communities)} communities (min-size {args.min_size})")

    def _do(c):
        ctx = community_context(c, nodes_by_id, graph["edges"], blocks_by_id)
        try:
            return c["community_id"], summarize(c, ctx, args.backend, args.model), None
        except Exception as e:   # one community failing must not discard the others
            return c["community_id"], "", {
                "community": c["name"], "size": c["size"], "prompt_chars": len(ctx),
                "error": f"{type(e).__name__}: {str(e)[:200]}"}

    results: dict[str, str] = {}
    failed: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for cid, summ, err in ex.map(_do, targets):
            if err:
                failed.append(err)
                print(f"  {cid}: FAILED ({err['error']})", file=sys.stderr)
                continue
            results[cid] = summ
            print(f"  {cid}: {len(summ)} chars")
    _report_failures(Path(args.communities).parent / "summaries_failed.json", failed, len(targets))

    for c in communities:
        if c["community_id"] in results:
            c["summary"] = results[c["community_id"]]

    Path(args.communities).write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    if args.load:
        comm.project(ArcadeDBStore(), communities)
        print("re-projected Community vertices with summaries")
    print(f"-> {args.communities}")


if __name__ == "__main__":
    main()
