"""How a table passage is shown to the answer step.

A table block is stored as its whole markdown (the section path first, then the rows). Cut to the first
characters it showed the model the column names and the first few rows, and the row that answered the question
was further down. Two properties of how documents store tables made that worse: Docling pads every column to its
widest cell, and a merged cell comes out once per column it spans. Neither says anything.

So a table is shown in three steps, all in code:
  1. the markup goes: padding, the separator line, a merged column repeated (read off the whole table), bold markers; a grid
     of marks (a matrix) is written row by row as `row: column=mark`, so a mark keeps the name of its column;
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
    """The cells of one row, in their columns: an empty cell stays (a matrix says something by what a column leaves empty)."""
    raw = line.split("\t") if "\t" in line and "|" not in line else line.strip().strip("|").split("|")
    return [re.sub(r"\s+", " ", c).strip() for c in raw]


def _unmerge(rows: list[list[str]]) -> list[list[str]]:
    """A merged cell comes out once per column it spans. That is read off the whole table, never one row: a column that
    repeats the one on its left in nearly every row is a merged column and goes; two equal cells in one row are not."""
    changed = True
    while changed and len(rows) >= 2:
        changed = False
        for j in range(max(len(r) for r in rows) - 1, 0, -1):
            both = [r for r in rows if len(r) > j]
            if len(both) >= 2 and sum(1 for r in both if r[j] and r[j] == r[j - 1]) >= 0.9 * len(both):
                rows = [r[:j] + r[j + 1:] if len(r) > j else r for r in rows]
                changed = True
                break
    return rows


def _bare(c: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", c)


def _row_text(cells: list[str]) -> str:
    """A row as one line. A cell set in bold on its own is a label: it goes first, as `label: value`. Empty cells are left out."""
    cells = [c for c in cells if c]
    labels = [m.group(1) for m in (_BOLD.match(c) for c in cells) if m]
    rest = [_bare(c) for c in cells if not _BOLD.match(c)]
    if labels and rest:
        return f"{' / '.join(labels)}: {' | '.join(rest)}"
    return " | ".join(_bare(c) for c in cells)


def _is_matrix(header: Optional[list[str]], rows: list[list[str]]) -> bool:
    """A grid of marks: wide, with a header, and mostly empty or one-to-three-character cells beyond the first column."""
    if not header or len(header) < 4 or not rows:
        return False
    cells = [c for r in rows for c in r[1:]]
    return bool(cells) and sum(1 for c in cells if len(c) <= 3) >= 0.4 * len(cells)


def _matrix_row(header: list[str], cells: list[str]) -> str:
    """`row name: column=mark; column=mark`: only the columns the row marks, each with the column's own name."""
    marks = [f"{_bare(header[j])}={_bare(c)}" for j, c in enumerate(cells) if j and c and j < len(header)]
    return f"{_bare(cells[0])}: " + ("; ".join(marks) if marks else "(no column marked)")


def parse(text: str) -> tuple[str, Optional[str], list[str]]:
    """(the lines before the table, its header row or None, its other rows) — each row already tidy."""
    lines = str(text or "").splitlines()
    first = next((i for i, x in enumerate(lines) if "|" in x or "\t" in x), len(lines))
    before = "\n".join(x for x in lines[:first] if x.strip())
    header, rows, seen_sep = None, [], False
    for x in lines[first:]:
        if not x.strip():
            continue
        if _SEPARATOR.match(x):
            if not seen_sep and rows:
                header, rows = rows[-1], rows[:-1]      # the row above the first separator is the header
            seen_sep = True
            continue
        cells = _cells(x)
        if any(cells):
            rows.append(cells)
    if header is not None:
        merged = _unmerge([header] + rows)
        header, rows = merged[0], merged[1:]
    else:
        rows = _unmerge(rows)
    matrix = _is_matrix(header, rows)
    out = [_matrix_row(header, r) if matrix else _row_text(r) for r in rows]
    return before, (" | ".join(_bare(c) for c in header if c) if header else None), out


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
