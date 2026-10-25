"""Step 1 — Parse DOCX into structural blocks (Docling).

Engine, not interface: `ingest_file(path) -> list[Block]` is the single entry
point. Today a CLI calls it over `docs/samples/`; later an upload endpoint calls
the same function. No DB, no network — it reads a file and writes block JSON.

How a block is identified: Docling parses the Word document's own structure and
yields typed elements in reading order (section headers, paragraphs, list items,
tables, pictures, captions). Each yielded element becomes one Block, normalized
into our type vocabulary and tagged with provenance. Tables are preserved as a
cell grid (+ markdown), not flattened — Step 1b depends on that.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from docling.document_converter import DocumentConverter

from eawiki.blocks import Block, load_blocks, save_blocks


def _label_value(item: Any) -> Optional[str]:
    lab = getattr(item, "label", None)
    return getattr(lab, "value", lab)


def _classify(item: Any) -> str:
    """Map a Docling item to one of our block types."""
    cls = type(item).__name__
    label = _label_value(item)
    if "Table" in cls or label == "table":
        return "table"
    if "Picture" in cls or label == "picture":
        return "figure"
    if label in ("section_header", "title") or "SectionHeader" in cls or "Title" in cls:
        return "heading"
    if label == "list_item" or "ListItem" in cls:
        return "list_item"
    if label == "caption":
        return "caption"
    if getattr(item, "text", None):
        return "paragraph"
    return "other"


def _extract_table(item: Any, doc: Any) -> dict[str, Any]:
    """Preserve table structure: a cell grid plus a markdown rendering."""
    markdown = ""
    for call in (lambda: item.export_to_markdown(doc), lambda: item.export_to_markdown()):
        try:
            markdown = call() or ""
            break
        except Exception:
            continue
    cells: list[list[str]] = []
    num_rows = num_cols = None
    try:
        data = item.data
        num_rows = getattr(data, "num_rows", None)
        num_cols = getattr(data, "num_cols", None)
        grid = getattr(data, "grid", None)
        if grid:
            for row in grid:
                cells.append([(getattr(c, "text", "") or "") for c in row])
    except Exception:
        pass
    return {"num_rows": num_rows, "num_cols": num_cols, "cells": cells, "markdown": markdown}


def _figure_caption(item: Any, doc: Any) -> str:
    for call in (lambda: item.caption_text(doc), lambda: item.caption_text()):
        try:
            return call() or ""
        except Exception:
            continue
    return ""


def _export_figure_image(item: Any, doc: Any, out_path: Path) -> bool:
    """Save a figure's pixels to out_path (PNG). Tries Docling's image API first,
    then a data-URI on item.image. Returns False (no crash) when the picture has
    no retrievable image — a `.docx` may reference an image Docling didn't keep."""
    try:
        from PIL import Image  # Docling pulls in Pillow
    except Exception:
        return False

    pil = None
    # 1) Docling's accessor (rendered or stored image)
    for getter in (lambda: item.get_image(doc),
                   lambda: getattr(getattr(item, "image", None), "pil_image", None)):
        try:
            pil = getter()
        except Exception:
            pil = None
        if pil is not None:
            break
    # 2) base64 data: URI on item.image.uri
    if pil is None:
        try:
            uri = getattr(getattr(item, "image", None), "uri", None)
            uri = str(uri) if uri is not None else ""
            if uri.startswith("data:"):
                import base64, io
                pil = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
        except Exception:
            pil = None
    if pil is None:
        return False

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pil.save(out_path)
        return True
    except Exception:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            pil.convert("RGB").save(out_path)
            return True
        except Exception:
            return False


def _page_no(item: Any) -> Optional[int]:
    prov = getattr(item, "prov", None)
    if prov:
        try:
            return prov[0].page_no
        except Exception:
            return None
    return None


def ingest_file(path: str | Path, image_dir: Optional[str | Path] = None,
                kind: str = "architecture") -> list[Block]:
    """Parse one document into an ordered list of structural blocks. When
    image_dir is given, each figure's pixels are exported to a PNG there and the
    path recorded on the block (figure.image_path) for the Step 3a vision pass.
    `kind` is the document class (architecture | motivation | governance |
    reference) stamped on every block and carried through the pipeline."""
    path = Path(path)
    doc_id = path.stem
    image_dir = Path(image_dir) if image_dir else None
    converter = DocumentConverter()
    doc = converter.convert(str(path)).document

    blocks: list[Block] = []
    heading_stack: list[tuple[int, str]] = []  # (level, text)
    ordinal = 0

    for entry in doc.iterate_items():
        item, level = (entry[0], entry[1]) if isinstance(entry, tuple) else (entry, 0)
        btype = _classify(item)
        text = (getattr(item, "text", "") or "").strip()
        table = figure = None

        if btype == "table":
            table = _extract_table(item, doc)
            text = table["markdown"]
        elif btype == "figure":
            cap = _figure_caption(item, doc)
            figure = {"caption": cap, "image_ref": getattr(item, "self_ref", None),
                      "image_path": None}
            if image_dir is not None:
                out_path = image_dir / f"{doc_id}-{ordinal}.png"
                if _export_figure_image(item, doc, out_path):
                    figure["image_path"] = str(out_path)
            text = cap

        # Skip genuinely empty blocks (no text, no structure).
        if not text and table is None and figure is None:
            continue

        heading_level = None
        if btype == "heading":
            heading_level = getattr(item, "level", None) or 1
            # pop siblings/deeper, then this heading's path = its ancestors
            while heading_stack and heading_stack[-1][0] >= heading_level:
                heading_stack.pop()
            section_path = [t for _, t in heading_stack]
            heading_stack.append((heading_level, text))
        else:
            section_path = [t for _, t in heading_stack]

        blocks.append(Block(
            block_id=f"{doc_id}:{ordinal}",
            doc_id=doc_id,
            source_file=str(path),
            ordinal=ordinal,
            type=btype,
            text=text,
            level=heading_level,
            section_path=section_path,
            table=table,
            figure=figure,
            self_ref=getattr(item, "self_ref", None),
            page_no=_page_no(item),
            kind=kind,
        ))
        ordinal += 1

    return blocks


def _parse_key(path: Path, kind: str) -> str:
    """What a parse depends on: the file's bytes, its id and class, and the parser version."""
    try:
        from importlib.metadata import version
        ver = version("docling")
    except Exception:
        ver = "?"
    h = hashlib.sha256(path.read_bytes())
    h.update(f"|{path.stem}|{kind}|docling-{ver}|v1".encode())
    return h.hexdigest()[:32]


def _cached_blocks(cache_file: Path, path: Path) -> Optional[list[Block]]:
    """Blocks from an earlier parse of the same bytes, or None. Refused when a figure image
    that the blocks point at is gone, so a cache hit never returns a dangling image."""
    if not cache_file.exists():
        return None
    try:
        blocks = load_blocks(cache_file)
        for b in blocks:
            ip = (b.figure or {}).get("image_path")
            if b.type == "figure" and ip and not Path(ip).exists():
                return None
            b.source_file = str(path)      # the folder may differ from the cached run
        return blocks
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 1 — parse DOCX into structural blocks")
    ap.add_argument("--in", dest="in_dir", default="docs/samples", help="input folder of .docx")
    ap.add_argument("--out", dest="out_dir", default="data/blocks", help="output folder for block JSON")
    ap.add_argument("--images", dest="image_dir", default="data/images",
                    help="output folder for exported figure images (PNG)")
    ap.add_argument("--kind", default="architecture",
                    choices=["architecture", "motivation", "governance", "reference"],
                    help="document class for this batch; a subfolder named like a kind overrides it")
    ap.add_argument("--no-cache", action="store_true",
                    help="re-parse every document even if an unchanged copy was parsed before")
    args = ap.parse_args()

    in_dir, out_dir = Path(args.in_dir), Path(args.out_dir)
    cache_dir = out_dir.parent / "graph" / "parse_cache"
    image_dir = Path(args.image_dir)
    known_kinds = {"architecture", "motivation", "governance", "reference"}
    # scan both the folder itself and one level of kind-named subfolders
    docx_files = sorted(in_dir.rglob("*.docx"))
    if not docx_files:
        print(f"no .docx files in {in_dir}", file=sys.stderr)
        sys.exit(1)

    grand_total = 0
    img_ok = img_miss = 0
    for path in docx_files:
        # a kind-named subfolder (docs/governance/x.docx) overrides --kind
        kind = path.parent.name if path.parent.name in known_kinds else args.kind
        cache_file = cache_dir / f"{_parse_key(path, kind)}.blocks.json"
        blocks = None if args.no_cache else _cached_blocks(cache_file, path)
        hit = blocks is not None
        if not hit:
            blocks = ingest_file(path, image_dir=image_dir, kind=kind)
        out_path = out_dir / f"{path.stem}.blocks.json"
        save_blocks(path.stem, str(path), blocks, out_path,
                    extra_meta={"parser": "docling"})
        if not hit:
            cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out_path, cache_file)
        counts: dict[str, int] = {}
        for b in blocks:
            counts[b.type] = counts.get(b.type, 0) + 1
            if b.type == "figure":
                if (b.figure or {}).get("image_path"):
                    img_ok += 1
                else:
                    img_miss += 1
        grand_total += len(blocks)
        print(f"{path.name:28s} -> {len(blocks):4d} blocks  {counts}  -> {out_path}"
              f"{'  (cached)' if hit else ''}")

    print(f"\nTOTAL: {grand_total} blocks across {len(docx_files)} docs")
    print(f"images exported: {img_ok} ok, {img_miss} with no retrievable image -> {image_dir}")


if __name__ == "__main__":
    main()
