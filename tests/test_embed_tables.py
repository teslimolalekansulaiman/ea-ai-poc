"""A long table is embedded row by row in windows (a description written from its first part cannot hold the rows after it); its
description says how long it is; a caption brings the table below it; Ask shows a long table tidied and cut to the rows that matter."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eawiki import describe, embed  # noqa: E402
from eawiki.blocks import Block  # noqa: E402
from eawiki.cases import passages as ps  # noqa: E402
from eawiki.query import answer as ans  # noqa: E402


def md_table(n, pad=60):
    head = f"| {'**Capability**'.ljust(pad)} | **Owner unit** | **Maturity** |\n|{'-' * (pad + 2)}|---------------|--------------|"
    rows = [f"| {('Capability %03d' % i).ljust(pad)} | OU-{10 + i % 9} | {i % 5 + 1} Documented |" for i in range(n)]
    rows[n - 7] = f"| {'Job Performance'.ljust(pad)} | OU-11 | 2 Documented |"
    return head + "\n" + "\n".join(rows)


def table_block(text, desc="This table lists capabilities. It covers only the first few."):
    return Block(block_id="D:5", doc_id="D", source_file="x", ordinal=5, type="table", text=text, section_path=["4. Catalogue"],
                 table={"num_rows": text.count("\n"), "num_cols": 3, "cells": [], "markdown": text}, description=desc)


def test_a_short_table_is_one_unit_as_before():
    units = embed.embeddable_units([table_block(md_table(8, 20))])
    assert len(units) == 1 and units[0]["id"] == "D:5" and "This table lists capabilities" in units[0]["embed_text"]


def test_a_long_table_is_embedded_in_windows_that_hold_every_row_once_with_the_header():
    text = md_table(60)
    units = embed.embeddable_units([table_block(text)])
    assert len(units) > 2 and [u["id"] for u in units] == [f"D:5#{i}" for i in range(len(units))] and all(u["block_id"] == "D:5" for u in units)
    assert all(u["n_chunks"] == len(units) and u["type"] == "table" for u in units)
    rows = [ln for u in units for ln in u["text"].splitlines() if ln.startswith("Capability ") or ln.startswith("Job Performance")]
    assert len(rows) == 60 and len(set(rows)) == 60                                       # every row, once
    assert all("Capability | Owner unit | Maturity" in u["text"] for u in units)             # the header row on every window
    win = next(u for u in units if "Job Performance" in u["text"])
    assert "Job Performance | OU-11 | 2 Documented" in win["embed_text"] and "  " not in win["text"].split("\n\n", 1)[1]      # tidied, and it is embedded
    assert win["embed_text"].count("This table lists capabilities.") == 1 and "It covers only the first few" not in win["embed_text"]    # the gist only
    assert "(rows " in win["text"] and " of 60)" in win["text"]


def test_the_description_of_a_long_table_says_it_is_only_the_beginning(monkeypatch):
    seen = []
    monkeypatch.setattr(describe, "llm_text", lambda p, backend, model: seen.append(p) or "A table of capabilities.")
    describe.describe_table(table_block(md_table(60)), "cli", None)
    assert "has 61 rows in all; only the beginning is shown" in seen[0] and "Do NOT describe the rows shown as if they were the whole table" in seen[0]
    seen.clear()
    describe.describe_table(table_block(md_table(5, 10)), "cli", None)
    assert "only the beginning is shown" not in seen[0]


def test_a_caption_above_a_table_brings_the_table_and_a_caption_below_a_figure_brings_the_figure():
    st = [{"block_id": "D:1", "doc_id": "D", "btype": "paragraph", "section": "5", "ordinal": 1, "text": "D > 5\nTable 10: Strategic objectives of the Organization"},
          {"block_id": "D:2", "doc_id": "D", "btype": "table", "section": "5", "ordinal": 2, "text": "D > 5\n| Code | Objective |\n| SO4 | Strengthen institutional excellence |\n| SO5 | Grow |"},
          {"block_id": "D:3", "doc_id": "D", "btype": "figure", "section": "5", "ordinal": 3, "text": "D > 5\n\nA heat map."},
          {"block_id": "D:4", "doc_id": "D", "btype": "paragraph", "section": "5", "ordinal": 4, "text": "D > 5\nFigure 1: Capability map"}]
    near = lambda bid, w: [r for r in st if abs(r["ordinal"] - int(bid.split(":")[1])) <= w]      # noqa: E731
    out, _, added = ps.reshape([st[0]], 3, near)
    got = [b for b in out if b.get("captioned")]
    assert added == 1 and got[0]["block_id"] == "D:2" and got[0]["btype"] == "table" and got[0]["via"] == "D:1" and not got[0]["figure"]
    out, _, _ = ps.reshape([st[3]], 3, near)
    assert [b["block_id"] for b in out if b.get("captioned")] == ["D:3"]                      # the figure before the caption, not the next block
    ctx = ans.assemble_context(out + [dict(got[0])], None, "which objective cuts manual work")
    assert "(the table that the caption [D:1] belongs to)" in ctx and "(the diagram that the caption [D:4] belongs to; this is its description)" in ctx


def test_ask_shows_a_long_table_tidied_and_cut_to_the_rows_that_matter():
    block = {"block_id": "D:5", "btype": "table", "section": "4", "text": "D > 4\n\n" + md_table(60)}
    ctx = ans.assemble_context([block], None, "who owns Job Performance")
    assert "Job Performance | OU-11 | 2 Documented" in ctx and len(ctx) < 3000 and "|----" not in ctx and "table of 60 rows" in ctx
