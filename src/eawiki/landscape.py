"""Step 9 — Overview / landscape wiki pages.

Narrative synthesis pages for whole areas, generated from the Step-8 community
summary + member nodes + their relationships + source blocks, and cited to source
blocks the same way entity pages are. These power the UI's Landscape/Map + Coverage
views. One page per community (above --min-size).

    python -m eawiki.landscape --min-size 4 --workers 6
Outputs: data/pages/landscape-<slug>.md
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eawiki.blocks import Block
from eawiki.subjects import llm_text
from eawiki.summaries import block_index, community_context


def build_page(c: dict, ctx: str, backend: str, model) -> str:
    summary = c.get("summary", "")
    prompt = f"""Write a LANDSCAPE wiki page (markdown) for this area of the enterprise architecture, for someone wanting the big picture. Use ONLY the context. Structure: '# {c['name']} Landscape', a short overview, the key systems/processes and how they connect, and risks/gaps. Cite block ids like [03-data:5]. Do not invent facts.

Existing summary of this area (you may build on it):
{summary or '(none)'}

{ctx}

Return ONLY the markdown page."""
    return llm_text(prompt, backend, model).strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 9 — landscape pages")
    ap.add_argument("--communities", default="data/graph/communities.json")
    ap.add_argument("--graph", default="data/graph/graph.json")
    ap.add_argument("--blocks", dest="in_dir", default="data/blocks")
    ap.add_argument("--pages", dest="pages_dir", default="data/pages")
    ap.add_argument("--min-size", type=int, default=4)
    ap.add_argument("--backend", default="cli")
    ap.add_argument("--model", default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    data = json.loads(Path(args.communities).read_text(encoding="utf-8"))
    communities = data["communities"]
    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    nodes_by_id = {n["node_id"]: n for n in graph["nodes"]}
    blocks_by_id: dict[str, Block] = block_index(args.in_dir)

    targets = [c for c in communities if c["size"] >= args.min_size]
    pages_dir = Path(args.pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    print(f"writing {len(targets)} landscape pages (min-size {args.min_size})")

    def _do(c):
        ctx = community_context(c, nodes_by_id, graph["edges"], blocks_by_id)
        return c, build_page(c, ctx, args.backend, args.model)

    written = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for c, page in ex.map(_do, targets):
            if page:
                (pages_dir / f"landscape-{c['slug']}.md").write_text(page + "\n", encoding="utf-8")
                written += 1
                print(f"  landscape-{c['slug']}.md  ({len(page)} chars)")

    print(f"\nlandscape pages: {written} -> {pages_dir}")


if __name__ == "__main__":
    main()
