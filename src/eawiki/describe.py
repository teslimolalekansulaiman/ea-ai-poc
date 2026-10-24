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

from eawiki.blocks import content_hash, load_blocks
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


def run(backend: str = "cli", model=None, in_dir: str = "data/blocks",
        cache_dir: str = "data/graph/desc_cache", use_cache: bool = True, force: bool = False) -> dict:
    # Sidecar cache keyed by the block's content_hash (+ backend/model): it lives OUTSIDE
    # data/blocks, so it survives the clean-rebuild wipe and an unchanged table/figure is
    # not re-described (no repeat vision calls) on re-ingest. Same idea as pages_cache.
    cdir = Path(cache_dir)
    gen = cached = n_skip = 0

    def _key(b):
        # content_hash alone collides for figures with identical/empty captions, so key
        # on block_id too, plus the image bytes for figures (so an image change invalidates).
        parts = [b.content_hash or "", b.block_id, b.type, backend, str(model)]
        if b.type == "figure":
            ip = (b.figure or {}).get("image_path")
            try:
                import hashlib
                parts.append(hashlib.sha1(Path(ip).read_bytes()).hexdigest()[:16]
                             if ip and Path(ip).exists() else "")
            except Exception:
                parts.append("")
        return content_hash(*parts)

    def _cache_get(b):
        cf = cdir / f"{_key(b)}.json"
        if cf.exists():
            try:
                return json.loads(cf.read_text(encoding="utf-8")).get("description")
            except Exception:
                return None
        return None

    def _cache_put(b):
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / f"{_key(b)}.json").write_text(
            json.dumps({"block_id": b.block_id, "type": b.type, "description": b.description},
                       ensure_ascii=False), encoding="utf-8")

    for fp in sorted(glob.glob(f"{in_dir}/*.blocks.json")):
        blocks = load_blocks(Path(fp))
        by_id = {}
        for b in blocks:
            if b.type not in ("table", "figure"):
                continue
            is_fig_no_img = b.type == "figure" and not ((b.figure or {}).get("image_path") and Path((b.figure or {}).get("image_path")).exists())
            if is_fig_no_img:
                n_skip += 1; continue

            # already in the file: warm the cache for future rebuilds, then move on
            if b.description and not force:
                if use_cache and not _cache_get(b):
                    _cache_put(b)
                continue
            # reuse a cached description (survives the block wipe)
            if use_cache and not force:
                hit = _cache_get(b)
                if hit:
                    b.description = hit; by_id[b.block_id] = hit; cached += 1
                    continue
            try:
                b.description = describe_table(b, backend, model) if b.type == "table" \
                    else describe_figure(b, backend, model)
                by_id[b.block_id] = b.description
                if use_cache:
                    _cache_put(b)
                gen += 1
                print(f"  {b.block_id:20s} {b.type:6s} {b.description[:88]}")
            except Exception as e:
                n_skip += 1
                print(f"  ! {b.block_id}: {type(e).__name__}: {str(e)[:110]}")
        if by_id:   # patch descriptions into the file, preserving all other fields
            payload = json.loads(Path(fp).read_text(encoding="utf-8"))
            for bd in payload["blocks"]:
                if bd["block_id"] in by_id:
                    bd["description"] = by_id[bd["block_id"]]
            Path(fp).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"described: {gen} generated, {cached} from cache  (skipped {n_skip})")
    return {"generated": gen, "cached": cached, "skipped": n_skip}


def main() -> None:
    ap = argparse.ArgumentParser(description="Describe tables & figures for semantic retrieval")
    ap.add_argument("--backend", default="cli")
    ap.add_argument("--model", default=None)
    ap.add_argument("--in", dest="in_dir", default="data/blocks")
    ap.add_argument("--cache-dir", default="data/graph/desc_cache")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-describe even if a description exists")
    a = ap.parse_args()
    run(a.backend, a.model, a.in_dir, a.cache_dir, not a.no_cache, a.force)


if __name__ == "__main__":
    main()
