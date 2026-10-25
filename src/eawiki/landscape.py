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
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from eawiki.blocks import Block, content_hash
from eawiki.subjects import effective_model, llm_text
from eawiki.summaries import _report_failures, block_index, community_context


def landscape_prompt(c: dict, ctx: str) -> str:
    summary = c.get("summary", "")
    return f"""Write a LANDSCAPE wiki page (markdown) for this area of the enterprise architecture, for someone wanting the big picture. Use ONLY the context. Structure: '# {c['name']} Landscape', a short overview, the key systems/processes and how they connect, and risks/gaps. Cite block ids like [03-data:5]. Do not invent facts.

Existing summary of this area (you may build on it):
{summary or '(none)'}

{ctx}

Return ONLY the markdown page."""


def build_page(c: dict, ctx: str, backend: str, model) -> str:
    return llm_text(landscape_prompt(c, ctx), backend, model).strip()


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
    ap.add_argument("--no-cache", action="store_true", help="regenerate every page")
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

    # Cached by the full prompt (which includes the community summary) + backend + model, so a
    # page is regenerated only when its community's members, evidence or summary changed.
    cdir = Path(args.communities).parent / "landscape_cache"

    def _do(c):
        ctx = community_context(c, nodes_by_id, graph["edges"], blocks_by_id)
        key = content_hash(landscape_prompt(c, ctx), args.backend, effective_model(args.model))
        cf = cdir / f"{key}.json"
        if not args.no_cache and cf.exists():
            try:
                return c, json.loads(cf.read_text(encoding="utf-8"))["page"], None, True
            except Exception:
                pass
        try:
            page = build_page(c, ctx, args.backend, args.model)
        except Exception as e:   # one community failing must not discard the others
            return c, "", {"community": c["name"], "size": c["size"], "prompt_chars": len(ctx),
                           "error": f"{type(e).__name__}: {str(e)[:200]}"}, False
        if page:
            cdir.mkdir(parents=True, exist_ok=True)
            cf.write_text(json.dumps({"page": page}, ensure_ascii=False), encoding="utf-8")
        return c, page, None, False

    written = reused = 0
    failed: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for c, page, err, hit in ex.map(_do, targets):
            if err:
                failed.append(err)
                print(f"  landscape-{c['slug']}: FAILED ({err['error']})", file=sys.stderr)
            elif page:
                (pages_dir / f"landscape-{c['slug']}.md").write_text(page + "\n", encoding="utf-8")
                written += 1
                reused += hit
                print(f"  landscape-{c['slug']}.md  ({len(page)} chars){'  (cached)' if hit else ''}")
    print(f"cache: reused {reused}   generated {written - reused}")
    _report_failures(Path(args.communities).parent / "landscape_failed.json", failed, len(targets))

    print(f"\nlandscape pages: {written} -> {pages_dir}")


if __name__ == "__main__":
    main()
