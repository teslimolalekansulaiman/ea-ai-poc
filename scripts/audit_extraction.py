"""Was a Word or PowerPoint file extracted fully? Compares each source file with its extracted blocks.

For every .docx / .pptx it counts what the file holds (tables, pictures, charts, SmartArt, text boxes and shapes, slides) and
what the extraction kept (table blocks, figure blocks with an image file, with a description), and checks every piece of text
in the file (a paragraph, a table cell, a text box, a slide shape, a note) against the text that was extracted. It also checks
that each table of the file survived AS A TABLE: the cells of its first row all sit in one table block. A table whose cells
came out as separate paragraphs has its text but has lost its rows.

No dependencies beyond the standard library; the Office files are read as the zip of XML they are.

    python scripts/audit_extraction.py --docs <folder of .docx/.pptx> --blocks <folder of *.blocks.json> [--json] [--show 12]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
PIC = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
WPS = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}"
C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
DGM = "{http://schemas.openxmlformats.org/drawingml/2006/diagram}"
V = "{urn:schemas-microsoft-com:vml}"
MIN_CHARS = 12          # a piece of text shorter than this is too easily found by accident to count


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*|`#_]+", " ", str(text or ""))).strip().casefold()


def _root(zf: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(zf.read(name))
    except (KeyError, ET.ParseError):
        return None


def _text(el, tag: str, skip: str = "") -> str:
    """The text of `el`; what sits inside a `skip` element (a text box in a paragraph) is not part of it."""
    if not skip:
        return "".join(t.text or "" for t in el.iter(tag))
    out = []
    for child in el:
        if child.tag == skip:
            continue
        out.append((child.text or "") if child.tag == tag else _text(child, tag, skip))
    return "".join(out)


def _parents(root) -> dict:
    return {c: p for p in root.iter() for c in p}


def _inside(el, parents: dict, tags: tuple) -> bool:
    while el in parents:
        el = parents[el]
        if el.tag in tags:
            return True
    return False


# ---- what the file holds ------------------------------------------------------------------------

def docx_inventory(path: Path) -> dict:
    inv = {"kind": "docx", "tables": [], "pictures": 0, "charts": 0, "smartart": 0, "textboxes": 0, "units": []}
    with zipfile.ZipFile(path) as zf:
        parts = [n for n in zf.namelist() if re.match(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$", n)]
        for part in parts:
            root = _root(zf, part)
            if root is None:
                continue
            par = _parents(root)
            inv["pictures"] += sum(1 for _ in root.iter(PIC + "pic")) + sum(1 for _ in root.iter(V + "imagedata"))
            inv["charts"] += sum(1 for e in root.iter(A + "graphicData") if "chart" in (e.get("uri") or ""))
            inv["smartart"] += sum(1 for _ in root.iter(DGM + "relIds"))
            boxes = list(root.iter(W + "txbxContent"))
            inv["textboxes"] += len(boxes)
            for box in boxes:
                t = _text(box, W + "t").strip()
                if t:
                    inv["units"].append(("text box", part, t))
            for tbl in root.iter(W + "tbl"):
                rows = []
                for tr in tbl.findall(W + "tr"):
                    cells = [_text(tc, W + "t", W + "tbl").strip() for tc in tr.findall(W + "tc")]
                    rows.append(cells)
                inv["tables"].append({"part": part, "rows": rows})
                for r in rows:
                    for c in r:
                        if c:
                            inv["units"].append(("table cell", part, c))
            for p in root.iter(W + "p"):
                if _inside(p, par, (W + "tbl", W + "txbxContent")):
                    continue
                t = _text(p, W + "t", W + "txbxContent").strip()
                if t:
                    inv["units"].append(("paragraph", part, t))
        inv["pictures_in_media"] = sum(1 for n in zf.namelist() if n.startswith("word/media/"))
    return inv


def pptx_inventory(path: Path) -> dict:
    inv = {"kind": "pptx", "tables": [], "pictures": 0, "charts": 0, "smartart": 0, "groups": 0, "slides": 0, "units": []}
    with zipfile.ZipFile(path) as zf:
        slides = sorted((n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
        inv["slides"] = len(slides)
        for part in slides + sorted(n for n in zf.namelist() if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n)):
            root = _root(zf, part)
            if root is None:
                continue
            notes = "notesSlides" in part
            inv["pictures"] += sum(1 for _ in root.iter(P + "pic"))
            inv["groups"] += sum(1 for _ in root.iter(P + "grpSp"))
            inv["charts"] += sum(1 for e in root.iter(A + "graphicData") if "chart" in (e.get("uri") or ""))
            inv["smartart"] += sum(1 for _ in root.iter(DGM + "relIds"))
            par = _parents(root)
            for tbl in root.iter(A + "tbl"):
                rows = [[_text(tc, A + "t").strip() for tc in tr.findall(A + "tc")] for tr in tbl.findall(A + "tr")]
                inv["tables"].append({"part": part, "rows": rows})
                for r in rows:
                    for c in r:
                        if c:
                            inv["units"].append(("table cell", part, c))
            for p in root.iter(A + "p"):
                if _inside(p, par, (A + "tbl",)):
                    continue
                t = _text(p, A + "t").strip()
                if t:
                    inv["units"].append(("note" if notes else "slide text", part, t))
        inv["pictures_in_media"] = sum(1 for n in zf.namelist() if n.startswith("ppt/media/"))
    return inv


# ---- what the extraction kept -------------------------------------------------------------------

def extracted(blocks_path: Path) -> dict:
    data = json.loads(blocks_path.read_text(encoding="utf-8"))
    blocks = data.get("blocks", [])
    table_texts, parts = [], []
    figures = images = described = 0
    for b in blocks:
        txt = " ".join(x for x in (b.get("text"), b.get("description"), (b.get("figure") or {}).get("caption")) if x)
        cells = ((b.get("table") or {}).get("cells") or [])
        if cells:
            txt += " " + " ".join(c for row in cells for c in row)
        parts.append(txt)
        if b.get("type") == "table":
            table_texts.append(norm(txt))
        if b.get("type") == "figure":
            figures += 1
            images += 1 if (b.get("figure") or {}).get("image_path") else 0
            described += 1 if (b.get("description") or "").strip() else 0
    return {"hay": norm(" ".join(parts)), "table_blocks": table_texts, "blocks": len(blocks), "figures": figures,
            "figures_with_image": images, "figures_described": described}


def audit(doc: Path, blocks: Path) -> dict:
    inv = docx_inventory(doc) if doc.suffix.lower() == ".docx" else pptx_inventory(doc)
    ex = extracted(blocks)
    hay = ex["hay"]
    units = [(k, w, t) for k, w, t in inv["units"] if len(norm(t)) >= MIN_CHARS]
    missing = [(k, w, t) for k, w, t in units if norm(t) not in hay]
    kept, lost = 0, []
    for t in inv["tables"]:
        first = [norm(c) for c in next((r for r in t["rows"] if sum(1 for c in r if c.strip()) >= 2), []) if c.strip()]
        if not first:
            continue                                  # a layout table with no row of two cells: nothing to keep as rows
        if any(all(c in tb for c in first) for tb in ex["table_blocks"]):
            kept += 1
        else:
            lost.append(" | ".join(first)[:100])
    return {"file": doc.name, "kind": inv["kind"], "source": {k: (len(v) if isinstance(v, list) else v) for k, v in inv.items()
                                                              if k not in ("units", "kind")},
            "extracted": {k: v for k, v in ex.items() if k not in ("hay", "table_blocks")} | {"table_blocks": len(ex["table_blocks"])},
            "text_units": len(units), "text_missing": len(missing), "missing": [(k, w, t[:110]) for k, w, t in missing],
            "tables_kept_as_tables": kept, "tables_not_kept": len(lost), "tables_not_kept_first_rows": lost}


def report(a: dict, show: int) -> str:
    s, e = a["source"], a["extracted"]
    n = a["text_units"]
    pct = 100.0 * (n - a["text_missing"]) / n if n else 100.0
    out = [f"\n{a['file']}"]
    out.append(f"  tables    : {s['tables']} in the file | {e['table_blocks']} table blocks | {a['tables_kept_as_tables']} kept as tables, {a['tables_not_kept']} not")
    out.append(f"  pictures  : {s['pictures']} in the file ({s.get('pictures_in_media', 0)} media files) | {e['figures']} figure blocks, "
               f"{e['figures_with_image']} with an image file, {e['figures_described']} described")
    extras = [f"{k} {s[k]}" for k in ("charts", "smartart", "textboxes", "groups", "slides") if s.get(k)]
    if extras:
        out.append("  also      : " + ", ".join(extras))
    out.append(f"  text      : {n} pieces of text in the file, {n - a['text_missing']} found in the extraction ({pct:.1f}%)")
    for k, w, t in a["missing"][:show]:
        out.append(f"    missing [{k}] {t!r}")
    if a["text_missing"] > show:
        out.append(f"    … and {a['text_missing'] - show} more")
    for t in a["tables_not_kept_first_rows"][:show]:
        out.append(f"    table not kept as a table, first row: {t}")
    flags = []
    if a["tables_not_kept"]:
        flags.append(f"{a['tables_not_kept']} table(s) lost their rows")
    if s["pictures"] > e["figures"]:
        flags.append(f"{s['pictures'] - e['figures']} picture(s) have no figure block")
    if e["figures"] > e["figures_with_image"]:
        flags.append(f"{e['figures'] - e['figures_with_image']} figure(s) have no image file")
    if e["figures_with_image"] > e["figures_described"]:
        flags.append(f"{e['figures_with_image'] - e['figures_described']} figure(s) with an image have no description")
    if s.get("charts") or s.get("smartart"):
        flags.append("charts or SmartArt may not be read: check them in the figures")
    if a["text_missing"]:
        flags.append(f"{a['text_missing']} piece(s) of text were not extracted")
    out.append("  verdict   : " + ("; ".join(flags) if flags else "nothing missing"))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--docs", required=True, help="folder of the source .docx / .pptx files")
    ap.add_argument("--blocks", required=True, help="folder of the extracted <document>.blocks.json files")
    ap.add_argument("--show", type=int, default=8, help="how many missing items to list per file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    results, skipped = [], []
    for f in sorted(Path(args.docs).iterdir()):
        if f.suffix.lower() not in (".docx", ".pptx") or f.name.startswith("~$"):
            continue
        b = Path(args.blocks) / f"{f.stem}.blocks.json"
        if not b.exists():
            skipped.append(f.name)
            continue
        try:
            results.append(audit(f, b))
        except Exception as ex:
            skipped.append(f"{f.name} ({type(ex).__name__}: {ex})")
    if args.json:
        print(json.dumps({"results": results, "skipped": skipped}, indent=2, ensure_ascii=False))
        return 0
    for a in results:
        print(report(a, args.show))
    for s in skipped:
        print(f"\nnot audited: {s} (no extracted blocks file for it, or it could not be read)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
