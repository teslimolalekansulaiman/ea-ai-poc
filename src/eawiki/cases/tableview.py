"""How a table passage is shown to the answer step.

A table block is stored as its whole markdown (the section path first, then the rows). Cut to the first
characters it showed the model the column names and the first few rows, and the row that answered the question
was further down. Two properties of how documents store tables made that worse: Docling pads every column to its
widest cell, and a merged cell comes out once per column it spans. Neither says anything.

So a table is shown in three steps, all in code:
  1. the markup goes: padding, the separator line, a merged cell repeated, bold markers;
  2. a table that still does not fit keeps its header and the rows that share the most distinctive words with what
     was asked (a word's weight is how few of the table's own rows carry it, so it needs no word list and no
     language), in the table's own order; a table with no matching row keeps its first rows;
  3. a cut table says so: how many rows it has and how many are shown.
"""

from __future__ import annotations

import math
import re
from typing import Optional

TABLE_CHARS = 2000          # a table's room in the evidence (a paragraph keeps its own, smaller, room)
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_BOLD = re.compile(r"^\*\*(.+?)\*\*$")
_WORD = re.compile(r"\w+", re.UNICODE)


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").lower()) if len(w) > 2}


def is_table(block: dict) -> bool:
    if block.get("btype") == "table":
        return True
    lines = [x for x in str(block.get("text") or "").splitlines() if x.strip()]
    return len(lines) >= 3 and sum(1 for x in lines if "|" in x or "\t" in x) >= len(lines) - 1


def _cells(line: str) -> list[str]:
    raw = line.split("\t") if "\t" in line and "|" not in line else line.strip().strip("|").split("|")
    out = []
    for c in raw:
        c = re.sub(r"\s+", " ", c).strip()
        if c and (not out or c != out[-1]):         # a merged cell comes once per column it spans
            out.append(c)
    return out


def _row_text(cells: list[str]) -> str:
    """A row as one line. A cell set in bold on its own is a label: it goes first, as `label: value`."""
    labels = [m.group(1) for m in (_BOLD.match(c) for c in cells) if m]
    rest = [c for c in cells if not _BOLD.match(c)]
    rest = [re.sub(r"\*\*(.+?)\*\*", r"\1", c) for c in rest]
    if labels and rest:
        return f"{' / '.join(labels)}: {' | '.join(rest)}"
    return " | ".join(re.sub(r"\*\*(.+?)\*\*", r"\1", c) for c in cells)


def parse(text: str) -> tuple[str, Optional[str], list[str]]:
    """(the lines before the table, its header row or None, its other rows) — each row already tidy."""
    lines = str(text or "").splitlines()
    first = next((i for i, x in enumerate(lines) if "|" in x or "\t" in x), len(lines))
    before = "\n".join(x for x in lines[:first] if x.strip())
    header, rows, seen_sep = None, [], False
    body = lines[first:]
    for i, x in enumerate(body):
        if not x.strip():
            continue
        if _SEPARATOR.match(x):
            if not seen_sep and rows:
                header, rows = rows[-1], rows[:-1]      # the row above the first separator is the header
            seen_sep = True
            continue
        cells = _cells(x)
        if cells:
            rows.append(_row_text(cells))
    return before, header, rows


def _weights(rows: list[str]) -> dict[str, float]:
    n = len(rows) or 1
    df: dict[str, int] = {}
    for r in rows:
        for w in words(r):
            df[w] = df.get(w, 0) + 1
    return {w: math.log(1 + n / c) for w, c in df.items()}


def pick(rows: list[str], query: str, room: int) -> tuple[list[int], bool]:
    """Indexes of the rows to show, in table order, and whether they were chosen by matching the question.
    Matching rows come best first until `room` characters are used; a table with no matching row gives its own first rows."""
    q = words(query)
    wt = _weights(rows)
    scored = sorted(((sum(wt.get(w, 0) for w in q & words(r)), -i) for i, r in enumerate(rows)), reverse=True)
    matching = [-neg for score, neg in scored if score > 0]
    order, matched = (matching, True) if matching else (list(range(len(rows))), False)
    chosen, used = [], 0
    for i in order:
        cost = len(rows[i]) + 1
        if used + cost > room and chosen:
            if matched:
                continue                      # a shorter matching row may still fit
            break
        chosen.append(i)
        used += cost
    return sorted(chosen), matched


def render(text: str, query: str = "", chars: int = TABLE_CHARS) -> str:
    before, header, rows = parse(text)
    head = [x for x in (before, header) if x]
    room = max(chars - sum(len(x) + 1 for x in head), 200)
    if sum(len(r) + 1 for r in rows) <= room:
        return "\n".join(head + rows)
    keep, matched = pick(rows, query, room)
    shown = [rows[i] for i in keep]
    note = (f"(table of {len(rows)} rows; {len(shown)} shown, the rest not shown"
            + (" — the rows closest to what was asked)" if matched else " — no row matched what was asked, so these are its first rows)"))
    return "\n".join(head + shown + [note])
