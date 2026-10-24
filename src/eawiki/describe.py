"""Natural-language descriptions for tables and figures, for semantic retrieval.

A table's raw markdown and a figure's image don't embed well, so this step generates a
short NL description of each — tables via a text model, figures via a vision model — and
stores it on the block (`description`). embed.py then embeds the DESCRIPTION (so a search
matches on meaning) while keeping the real content as the block text, so when a table or
figure is retrieved its actual content/description is added to the answer context.

Descriptions are cached on the block: a block is re-described only when it has none (or
--force), so re-ingests don't re-pay for unchanged tables/figures.

    python -m eawiki.describe --backend openrouter          # tables (text) + figures (vision)
    python -m eawiki.describe --backend openrouter --force   # redo all
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

from eawiki.blocks import load_blocks
from eawiki.subjects import llm_text, llm_vision


def _section(b) -> str:
    return " / ".join(b.section_path) or "(root)"


def describe_table(b, backend: str, model) -> str:
    prompt = (
        "Describe this table in 2-3 sentences so it can be found by search: say what it "
        "lists, its columns, and the specific entities/subjects it covers (use their names). "
        "Plain text only, no preamble.\n\n"
        f"Section: {_section(b)}\n\nTable (markdown):\n{(b.text or '').strip()[:2200]}\n\nDescription:")
    return llm_text(prompt, backend, model).strip()


def describe_figure(b, backend: str, model) -> str:
    fig = b.figure or {}
    prompt = (
        "Describe this enterprise-architecture diagram in 2-4 sentences so it can be found "
        "by search: what it depicts, the main components/boxes shown, and how they connect. "
        "Name specific elements you can read. Plain text only, no preamble.\n\n"
        f"Caption: {fig.get('caption') or '(none)'}\nSection: {_section(b)}\n\nDescription:")
    return llm_vision(prompt, fig.get("image_path"), backend, model).strip()


def run(backend: str = "cli", model=None, in_dir: str = "data/blocks", force: bool = False) -> dict:
    n_t = n_f = n_skip = 0
    for fp in sorted(glob.glob(f"{in_dir}/*.blocks.json")):
        blocks = load_blocks(Path(fp))
        by_id = {}
        for b in blocks:
            if b.type not in ("table", "figure"):
                continue
            if b.description and not force:
                continue
            try:
                if b.type == "table":
                    b.description = describe_table(b, backend, model); n_t += 1
                elif (b.figure or {}).get("image_path") and Path((b.figure or {}).get("image_path")).exists():
                    b.description = describe_figure(b, backend, model); n_f += 1
                else:
                    n_skip += 1; continue
                by_id[b.block_id] = b.description
                print(f"  {b.block_id:20s} {b.type:6s} {b.description[:90]}")
            except Exception as e:
                n_skip += 1
                print(f"  ! {b.block_id}: {type(e).__name__}: {str(e)[:110]}")
        if by_id:   # patch descriptions into the file, preserving all other fields
            payload = json.loads(Path(fp).read_text(encoding="utf-8"))
            for bd in payload["blocks"]:
                if bd["block_id"] in by_id:
                    bd["description"] = by_id[bd["block_id"]]
            Path(fp).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"described: {n_t} tables, {n_f} figures  (skipped {n_skip})")
    return {"tables": n_t, "figures": n_f, "skipped": n_skip}


def main() -> None:
    ap = argparse.ArgumentParser(description="Describe tables & figures for semantic retrieval")
    ap.add_argument("--backend", default="cli")
    ap.add_argument("--model", default=None)
    ap.add_argument("--in", dest="in_dir", default="data/blocks")
    ap.add_argument("--force", action="store_true", help="re-describe even if a description exists")
    a = ap.parse_args()
    run(a.backend, a.model, a.in_dir, a.force)


if __name__ == "__main__":
    main()
