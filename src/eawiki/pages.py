"""Step 3a (text half) — write each subject's wiki page + extract prose triples.

For each subject, ONE LLM pass over its TEXT blocks (the full-context bundle Step 2
gathered; figures are handled by figures.py) — with the subject's Step 1b table
facts injected — produces two things from one reading:
  1. the wiki PAGE  — a grounded markdown synthesis, citing block ids inline;
  2. the TRIPLES    — relationships it found, each with a source block id and a
     quoted span, validated against the metamodel source->target triples.

The page is the product; the graph is the byproduct. Backend is the pluggable
cli (`claude -p`) / sdk, same as the other steps.

Outputs:
  data/pages/<slug>.md       — the wiki page
  data/graph/facts_3a.json   — {nodes, edges} with evidence + block_id

    python -m eawiki.pages --menu data/togaf92_metamodel.json --backend cli [--only "Customer Portal"] [--limit N]
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from eawiki.blocks import Block, load_blocks
from eawiki.subjects import llm_text, _extract_json, _norm, llm_json
from eawiki.tables import _vocab, _validate_llm_facts, _SECURITY_RULE, _PREDICATE_RULE


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "subject"


def _subject_blocks(subject: dict, by_id: dict[str, Block]) -> str:
    """The subject's TEXT blocks (skip figures), id :: section :: text."""
    lines = []
    for bid in subject.get("block_ids", []):
        b = by_id.get(bid)
        if b is None or b.type == "figure":
            continue
        txt = (b.text or "").strip()
        if not txt:
            continue
        sect = " / ".join(b.section_path) or "(root)"
        lines.append(f"[{bid}] ({sect})\n{txt[:800]}")
    return "\n\n".join(lines) or "(no text blocks)"


def _injected_facts(name: str, facts_1b: dict) -> str:
    """The subject's already-known table facts, so the page weaves them in and
    the model doesn't have to re-derive them from the raw table markdown."""
    key = _norm(name)
    edges = [f"{e['source']} --{e['relation']}--> {e['target']}"
             for e in facts_1b.get("edges", [])
             if _norm(e["source"]) == key or _norm(e["target"]) == key]
    attrs = [f"{a['name']} = {a['value']}"
             for a in facts_1b.get("attributes", []) if _norm(a["subject"]) == key]
    out = []
    if edges:
        out.append("relationships: " + "; ".join(sorted(set(edges))))
    if attrs:
        out.append("attributes: " + "; ".join(sorted(set(attrs))))
    return "\n".join(out) or "(none from tables)"


def extract_page(subject: dict, by_id: dict[str, Block], facts_1b: dict,
                 menu: dict, backend: str, model) -> dict:
    name, stype, kind = subject["name"], subject.get("type"), subject.get("kind")
    prompt = f"""You are writing ONE page of an enterprise-architecture wiki, and extracting the relationships it states. Output ONE JSON object and nothing else.

Subject: "{name}"  (type: {stype}, kind: {kind})

{_vocab(menu)}

Already-known facts about this subject (from structured tables — treat as true; weave them into the page and include them as edges if a block supports them):
{_injected_facts(name, facts_1b)}

Source blocks for this subject (id :: section :: text) — the full context:
{_subject_blocks(subject, by_id)}

Return ONE JSON object:
{{
  "page_markdown": "<a full, readable wiki page about the subject: start with '# {name}', then a summary, what it is, how it relates to other things, and any context / rationale / risks the blocks support. Cite blocks inline like [03-data:5]. Plain markdown; escape newlines as \\n inside this JSON string.>",
  "edges": [{{"source": "<text>", "source_type": "<NODE TYPE>", "relation": "<EDGE TYPE>",
              "target": "<text>", "target_type": "<NODE TYPE>",
              "access_type": "<only for an accesses edge>",
              "evidence": "<quoted span from a block>", "block_id": "<the block it came from>"}}],
  "nodes": [{{"name": "<a NEW entity this page introduces, if any>", "type": "<NODE TYPE>",
              "evidence": "<quoted span>", "block_id": "<block>"}}]
}}

Rules:
- The PAGE is the product: write it fully and readably from the blocks; it is NOT limited to what the edges capture.
- Extract an edge ONLY when a block states or clearly implies it; put the quoted span in `evidence` and the citing block id in `block_id`. No quote -> no edge.
- Use ONLY the node/edge types above; respect each edge's allowed source->target. If a real link fits none, use `associated_with`.
- The subject is usually one endpoint of its edges; use the subject's own type for that endpoint.
- Do not invent facts not in the blocks; ignore scaffolding (Purpose/Overview headings).
{_SECURITY_RULE}
{_PREDICATE_RULE}"""

    out = llm_json(prompt, backend, model)
    if not isinstance(out, dict):
        raise ValueError("page extractor did not return a JSON object")
    out.setdefault("page_markdown", "")
    out.setdefault("edges", [])
    out.setdefault("nodes", [])
    _validate_llm_facts(menu, out["nodes"], out["edges"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 3a (text) — wiki pages + prose triples")
    ap.add_argument("--in", dest="in_dir", default="data/blocks")
    ap.add_argument("--subjects", default="data/graph/subjects.json")
    ap.add_argument("--facts1b", default="data/graph/facts_1b.json")
    ap.add_argument("--menu", default="data/togaf92_metamodel.json")
    ap.add_argument("--pages", dest="pages_dir", default="data/pages")
    ap.add_argument("--out", dest="out", default="data/graph/facts_3a.json")
    ap.add_argument("--backend", default="cli", choices=["cli", "sdk", "openai", "openrouter", "pulse"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", default=None, help="run a single subject by name")
    ap.add_argument("--limit", type=int, default=0, help="cap number of subjects (0 = all)")
    ap.add_argument("--workers", type=int, default=6,
                    help="concurrent subjects (each is one claude -p call); 1 = sequential")
    args = ap.parse_args()

    menu = json.loads(Path(args.menu).read_text(encoding="utf-8"))
    facts_1b = json.loads(Path(args.facts1b).read_text(encoding="utf-8"))
    subjects = json.loads(Path(args.subjects).read_text(encoding="utf-8"))

    by_id: dict[str, Block] = {}
    for fp in sorted(glob.glob(f"{args.in_dir}/*.blocks.json")):
        for b in load_blocks(Path(fp)):
            by_id[b.block_id] = b

    if args.only:
        subjects = [s for s in subjects if _norm(s["name"]) == _norm(args.only)]
    if args.limit:
        subjects = subjects[:args.limit]

    pages_dir = Path(args.pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[dict, dict]] = []  # (subject, out)
    written = 0

    def _do(s: dict) -> tuple[dict, dict]:
        return s, extract_page(s, by_id, facts_1b, menu, args.backend, args.model)

    # Each subject is an independent claude -p call -> run them concurrently.
    # Page files have distinct paths (write in worker); facts are collected and
    # written once, in the main thread, after all workers finish.
    workers = max(1, args.workers)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_do, s): s for s in subjects}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                _, out = fut.result()
            except Exception as exc:
                print(f"  ! {s['name']}: failed ({type(exc).__name__}: {str(exc)[:90]}) — skipped")
                continue
            page = out["page_markdown"].strip()
            if page:
                (pages_dir / f"{_slug(s['name'])}.md").write_text(page + "\n", encoding="utf-8")
                written += 1
            results.append((s, out))
            print(f"  {s['name']:32s} page={'yes' if page else 'no ':3}  "
                  f"edges={len(out['edges']):2d}  nodes+={len(out['nodes'])}")

    # Stable, review-friendly output: order facts by subject, not completion order.
    results.sort(key=lambda r: r[0]["name"].lower())
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    for s, out in results:
        prov = {"subject": s["name"], "origin": "3a-text"}
        all_nodes += [{**n, **prov} for n in out["nodes"] if n.get("name")]
        all_edges += [{**e, **prov} for e in out["edges"] if e.get("source") and e.get("target")]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"nodes": all_nodes, "edges": all_edges}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\npages written: {written} -> {pages_dir}")
    print(f"3a text facts: {len(all_nodes)} nodes, {len(all_edges)} edges -> {args.out}")


if __name__ == "__main__":
    main()
