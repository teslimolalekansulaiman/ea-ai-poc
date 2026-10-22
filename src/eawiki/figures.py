"""Step 3a (vision half) — extract graph facts from figure images.

For each figure block that has an exported `image_path` (see parse.py --images),
a vision-capable LLM reads the DIAGRAM together with its surrounding text context
and returns schema-valid {nodes, edges}, validated against the metamodel triples
exactly like the table / prose paths. The backend is the pluggable cli
(`claude -p`, which reads the image file by path) or sdk.

Output: data/graph/facts_figures.json — merged with facts_1b and the 3a text
facts in Step 4. Run after Step 1 (parse --images) and Step 2.

    python -m eawiki.figures --menu data/togaf92_metamodel.json --backend cli
"""

from __future__ import annotations

import argparse
import glob
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eawiki.blocks import Block, load_blocks
from eawiki.subjects import llm_text, _extract_json, _norm, llm_json
from eawiki.tables import _vocab, _validate_llm_facts, _SECURITY_RULE


def _context_for_figure(fig: Block, all_blocks: list[Block]) -> str:
    """Caption + the text of every block in the figure's section + its immediate
    neighbours — so the model can resolve diagram labels to full names/types."""
    sect = tuple(fig.section_path)
    lines: list[str] = []
    cap = (fig.figure or {}).get("caption") or ""
    if cap.strip():
        lines.append(f"caption: {cap.strip()}")
    for b in all_blocks:
        if b.block_id == fig.block_id:
            continue
        near = abs(b.ordinal - fig.ordinal) <= 2 and b.doc_id == fig.doc_id
        same_section = b.section_path and tuple(b.section_path) == sect
        txt = (b.text or "").strip()
        if (near or same_section) and txt and b.type != "figure":
            lines.append(f"[{b.block_id}] {txt[:300]}")
    return "\n".join(lines) or "(no surrounding text)"


def extract_figure(fig: Block, all_blocks: list[Block], menu: dict,
                   backend: str, model) -> dict:
    """Vision-read one figure -> schema-valid {nodes, edges} with evidence."""
    image_path = (fig.figure or {}).get("image_path")
    if not image_path or not Path(image_path).exists():
        raise FileNotFoundError(f"no image for {fig.block_id}: {image_path!r}")

    prompt = f"""You read ONE enterprise-architecture DIAGRAM image and extract the entities (boxes) and relationships (arrows/lines) it shows, mapped to the schema below. Output ONE JSON object and nothing else.

First, read the image file at: {image_path}

{_vocab(menu)}

Context around the figure (caption + surrounding text) — use it to resolve short diagram labels to their proper names and types:
{_context_for_figure(fig, all_blocks)}

Return ONE JSON object:
{{
  "nodes": [{{"name": "<box label, resolved to its full name>", "type": "<one NODE TYPE>", "evidence": "<what you saw, e.g. 'box labelled Customer Portal'>"}}],
  "edges": [{{"source": "<text>", "source_type": "<NODE TYPE>", "relation": "<EDGE TYPE>",
              "target": "<text>", "target_type": "<NODE TYPE>",
              "access_type": "<only for an accesses edge>",
              "evidence": "<what you saw, e.g. 'arrow from Customer Portal to Payment Gateway'>"}}]
}}

Rules:
- Each box / labelled shape is a node; map it to the closest NODE TYPE, using the context for its proper name and type.
- Extract an edge ONLY when the diagram shows an ACTUAL connection — a drawn arrow or line between two boxes. If there are NO visible arrows/lines, return "edges": [] — never infer a connection from mere left-to-right ordering or proximity.
- Respect each edge's allowed source->target types; if a real connection fits none, use `associated_with`.
- Every node and edge needs an `evidence` note describing what you saw in the image.
{_SECURITY_RULE}"""

    out = llm_json(prompt, backend, model)
    if not isinstance(out, dict):
        raise ValueError("vision extractor did not return a JSON object")
    out.setdefault("nodes", [])
    out.setdefault("edges", [])
    # reuse the shared validator (it keys on `type`/`relation` + source/target types)
    _validate_llm_facts(menu, out["nodes"], out["edges"])
    return out


def facts_from_figure(fig: Block, out: dict) -> tuple[list[dict], list[dict]]:
    """Attach provenance to vision-extracted facts (parallels tables.facts_from_llm)."""
    prov = {"block_id": fig.block_id, "doc_id": fig.doc_id,
            "section_path": fig.section_path, "origin": "figure-vision",
            "image_path": (fig.figure or {}).get("image_path")}
    nodes = [{"name": n["name"], "type": n["type"], "evidence": n.get("evidence", ""),
              **({"note": n["note"]} if n.get("note") else {}), **prov}
             for n in out["nodes"] if n.get("name")]
    edges = [{"source": e["source"], "source_type": e["source_type"], "relation": e["relation"],
              "target": e["target"], "target_type": e["target_type"],
              **({"access_type": e["access_type"]} if e.get("access_type") else {}),
              "evidence": e.get("evidence", ""), "validation": e.get("validation", "ok"),
              **({"note": e["note"]} if e.get("note") else {}), **prov}
             for e in out["edges"] if e.get("source") and e.get("target")]
    return nodes, edges


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 3a (vision) — extract graph facts from figure images")
    ap.add_argument("--in", dest="in_dir", default="data/blocks")
    ap.add_argument("--menu", dest="menu", default="data/togaf92_metamodel.json")
    ap.add_argument("--out", dest="out", default="data/graph/facts_figures.json")
    ap.add_argument("--backend", default="cli", choices=["cli", "sdk", "openai", "openrouter", "pulse"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--workers", type=int, default=6,
                    help="concurrent figures (each is one vision claude -p call); 1 = sequential")
    args = ap.parse_args()

    menu = json.loads(Path(args.menu).read_text(encoding="utf-8"))
    all_blocks: list[Block] = []
    for fp in sorted(glob.glob(f"{args.in_dir}/*.blocks.json")):
        all_blocks += load_blocks(Path(fp))

    figures = [b for b in all_blocks if b.type == "figure" and (b.figure or {}).get("image_path")]
    skipped = [b for b in all_blocks if b.type == "figure" and not (b.figure or {}).get("image_path")]
    print(f"figures with images: {len(figures)}  (skipped, no image: {len(skipped)})")

    # Each figure is an independent vision call -> process the set concurrently,
    # then aggregate in stable (reading) order so the output is diffable.
    def _process_figure(fig: Block) -> dict:
        try:
            out = extract_figure(fig, all_blocks, menu, args.backend, args.model)
            n, e = facts_from_figure(fig, out)
            return {"fig": fig, "n": n, "e": e}
        except Exception as ex:
            return {"fig": fig, "error": ex}

    workers = max(1, args.workers)
    by_id: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(_process_figure, figures):
            by_id[res["fig"].block_id] = res

    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    for fig in figures:
        res = by_id[fig.block_id]
        if "error" in res:
            ex = res["error"]
            print(f"  ! {fig.block_id}: vision failed ({type(ex).__name__}: {str(ex)[:100]}) — skipped")
            continue
        all_nodes += res["n"]
        all_edges += res["e"]
        print(f"  {fig.block_id:<20} -> {len(res['n'])} nodes, {len(res['e'])} edges")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(
        {"nodes": all_nodes, "edges": all_edges}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nfigure facts: {len(all_nodes)} nodes, {len(all_edges)} edges -> {args.out}")


if __name__ == "__main__":
    main()
