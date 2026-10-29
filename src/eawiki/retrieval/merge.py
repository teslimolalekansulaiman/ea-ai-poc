"""The retrieval merge (docs/RETRIEVAL_MERGE_SPEC.md): what the answer step is shown, in what order, and how complete each piece is.

Pure Python. The lanes (tables, wiki, graph, figures, text) are searched elsewhere and their results are passed in; a function that
fetches the missing parts of a table is passed in too. Nothing here calls a model or an index. It decides STRUCTURE only: which results
fit, which table parts are missing and need fetching, what is dropped when the evidence is too long, and what each section says about
how complete it is. What the evidence means, and which source wins when two disagree, stays with the model and the property's own text.

    sections = merge([LaneResult("tables", [...]), LaneResult("wiki", [...]), ...], fetch_parts=fetch)
    prompt_part = render(sections, question)
    allowed_citations = sections.allowed
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Optional

from eawiki.cases import tableview

# Priority for room: who fills its slots first and who gives way last. Not the order of authority: that is the property's own text.
PRIORITY = ("tables", "wiki", "graph", "figures", "text")
HEADINGS = {"tables": "TABLES", "wiki": "WIKI PAGES", "graph": "GRAPH FACTS", "figures": "FIGURES", "text": "TEXT"}


@dataclass(frozen=True)
class Budget:
    """The limits of one merge. Proposed numbers of the spec; a property may override them with dataclasses.replace."""
    results: dict = field(default_factory=lambda: {"tables": 3, "wiki": 3, "graph": 30, "figures": 3, "text": 5})
    table_chars: int = 6000            # all the tables together
    small_table_parts: int = 4         # a table of at most this many parts ...
    small_table_chars: int = 4000      # ... and about this many characters is completed whenever one part is found
    passage_chars: int = 1100          # one text passage (a run read after a label: run_chars)
    run_chars: int = 1800
    figure_chars: int = 2500
    wiki_chars: int = 2500
    total_chars: int = 20000


@dataclass
class Item:
    """One result. `id` is what the answer may cite (a block id, or wiki:<slug>); `cites` lists more ids a graph item rests on."""
    lane: str
    id: str
    text: str
    part: int = 1
    parts: int = 1
    rows_from: Optional[int] = None
    rows_to: Optional[int] = None
    rows_total: Optional[int] = None
    cites: tuple = ()
    meta: dict = field(default_factory=dict)

    def key(self) -> tuple:
        return (self.id, self.part)


@dataclass
class LaneResult:
    """What one lane found. `items` nearest first; `searched` is how many it returned before any limit (0 = same as len(items)).
    state: found | none | error | not_searched. `extra` carries what the lane set aside ({'labels_set_aside': 2})."""
    lane: str
    items: list = field(default_factory=list)
    state: str = "found"
    searched: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class Section:
    lane: str
    heading: str
    completeness: str
    items: list
    complete: bool = True


@dataclass
class Merged:
    sections: list
    allowed: set
    dropped: dict = field(default_factory=dict)            # lane -> how many results the budget took out


def _size(it: Item) -> int:
    return len(it.text or "")


def _cap(it: Item, b: Budget) -> Item:
    """The item with its text cut to the lane's room, marked when cut."""
    limit = {"text": b.run_chars if it.meta.get("run") else b.passage_chars, "figures": b.figure_chars, "wiki": b.wiki_chars}.get(it.lane)
    if limit and _size(it) > limit:
        return replace(it, text=it.text[:limit].rstrip() + " …", meta={**it.meta, "cut": True})
    return it


def _row_range(parts: list[Item]) -> str:
    got = [p for p in parts if p.rows_from is not None and p.rows_to is not None]
    if not got:
        return ""
    total = next((p.rows_total for p in got if p.rows_total), None)
    spans, start, end = [], None, None
    for p in sorted(got, key=lambda x: x.rows_from):
        if start is None:
            start, end = p.rows_from, p.rows_to
        elif p.rows_from == end + 1:
            end = p.rows_to
        else:
            spans.append((start, end))
            start, end = p.rows_from, p.rows_to
    spans.append((start, end))
    text = " and ".join(f"{a} to {z}" for a, z in spans)
    return f"rows {text}" + (f" of {total}" if total else "")


def _part_range(nums: list[int]) -> str:
    nums = sorted(set(nums))
    spans, start, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n != prev + 1:
            spans.append((start, prev))
            start = n
        prev = n
    spans.append((start, prev))
    return ", ".join(str(a) if a == z else f"{a} to {z}" for a, z in spans)


# ---- tables ---------------------------------------------------------------------------------------

def _complete_tables(items: list[Item], b: Budget, fetch: Optional[Callable], whole: bool) -> tuple[list[Item], list[str]]:
    """The table results, grouped by table (in the order of the best part of each) and completed as the spec says. Returns the items to
    show, parts in order, and one note per table that is not complete."""
    groups: dict = {}
    for it in items:
        groups.setdefault(it.id, []).append(it)
    out, notes, used = [], [], 0
    for bid, found in list(groups.items())[:b.results["tables"]]:
        n = max(x.parts for x in found)
        have = {x.part: x for x in found}
        est = (sum(_size(x) for x in found) / len(found)) * n
        small = n <= b.small_table_parts and est <= b.small_table_chars
        if n > 1 and (small or whole):
            want = [p for p in range(1, n + 1) if p not in have]
        elif n > 1:
            want = sorted({q for p in have for q in (p - 1, p + 1) if 1 <= q <= n and q not in have})
        else:
            want = []
        got, err = [], ""
        if want:
            if fetch is None:
                err = "the other parts could not be fetched"
            else:
                try:
                    got = [x for x in (fetch(bid, want) or []) if x.part in want]
                except Exception:
                    err = "the other parts could not be fetched (error)"
        for x in got:
            have.setdefault(x.part, x)
        # the table's room: a part is never cut; what does not fit is left out and said
        parts, skipped = [], []
        for p in sorted(have):
            if used + _size(have[p]) > b.table_chars and parts:
                skipped.append(p)
                continue
            if used + _size(have[p]) > b.table_chars and not parts and out:
                skipped.append(p)
                continue
            parts.append(have[p])
            used += _size(have[p])
        if not parts:
            notes.append(f"table [{bid}] not shown (the table budget is used)")
            continue
        out += parts
        shown = [x.part for x in parts]
        if n > 1 and set(shown) != set(range(1, n + 1)):
            why = err or ("the table budget stopped it" if skipped else "")
            rr = _row_range(parts)
            notes.append(f"table [{bid}]: parts {_part_range(shown)} of {n} shown" + (f"; {rr}" if rr else "") + (f" ({why})" if why else ""))
    return out, notes


# ---- the merge ------------------------------------------------------------------------------------

def merge(lanes: list[LaneResult], budget: Optional[Budget] = None, fetch_parts: Optional[Callable] = None, whole_tables: bool = False) -> Merged:
    """Collect, complete the tables, remove duplicates, keep within the budget, label. `fetch_parts(block_id, [part numbers])` returns the
    Items of those parts of a table (or raises)."""
    b = budget or Budget()
    by_lane = {r.lane: r for r in lanes}
    taken: dict = {}                 # lane -> (items, notes, result)
    seen: dict = {}                  # (id, part) -> the lane that has it
    for lane in PRIORITY:
        r = by_lane.get(lane)
        if r is None:
            r = LaneResult(lane, [], "not_searched")
        items = list(r.items) if r.state == "found" else []
        notes: list[str] = []
        if lane == "tables":
            items, notes = _complete_tables(items, b, fetch_parts, whole_tables)
        else:
            items = items[:b.results.get(lane, len(items))]
        kept = []
        for it in items:
            if it.key() in seen:                         # the same piece found by a higher-priority lane: shown there, once
                first = seen[it.key()]
                for sec_item in taken[first][0]:
                    if sec_item.key() == it.key():
                        sec_item.meta.setdefault("also_found_in", []).append(lane)
                continue
            seen[it.key()] = lane
            kept.append(_cap(it, b))
        taken[lane] = (kept, notes, r)
    dropped = _within_budget(taken, b)
    sections, allowed = [], set()
    for lane in PRIORITY:
        kept, notes, r = taken[lane]
        sections.append(_section(lane, kept, notes, r, dropped.get(lane, 0)))
        for it in kept:
            allowed.add(it.id)
            allowed.update(it.cites)
    return Merged(sections, allowed, dropped)


def _within_budget(taken: dict, b: Budget) -> dict:
    """When the evidence is longer than the budget, the lowest-priority lane gives up first and, inside a lane, its last result first. A table
    goes as a whole, never part by part."""
    dropped: dict = {}
    total = sum(_size(it) for kept, _, _ in taken.values() for it in kept)
    for lane in reversed(PRIORITY):
        kept = taken[lane][0]
        while total > b.total_chars and kept:
            if lane == "tables":
                last = kept[-1].id
                gone = [x for x in kept if x.id == last]
                kept[:] = [x for x in kept if x.id != last]
            else:
                gone = [kept.pop()]
            total -= sum(_size(x) for x in gone)
            dropped[lane] = dropped.get(lane, 0) + (1 if lane == "tables" else len(gone))
    return dropped


def _section(lane: str, kept: list, notes: list, r: LaneResult, dropped: int) -> Section:
    heading = HEADINGS[lane]
    if r.state == "not_searched":
        return Section(lane, f"{heading} (not searched for this question)", "not searched for this question", [])
    if r.state == "error":
        return Section(lane, f"{heading} (could not be searched)", "could not be searched (error): nothing can be concluded from its silence", [], False)
    if r.state == "none" or (not r.items and r.state == "found"):
        extra = _extra(r)
        return Section(lane, f"{heading} (none found)", "none found" + extra, [])
    searched = r.searched or (len({it.id for it in r.items}) if lane == "tables" else len(r.items))      # a table is one result whatever its parts
    shown = len({it.id for it in kept}) if lane == "tables" else len(kept)
    bits = [f"{searched} searched; {shown} shown" if searched != shown else f"{shown} shown"]
    complete = True
    if dropped:
        bits.append(f"{dropped} not shown (budget)")
        complete = False
    bits += notes
    if notes:
        complete = False
    bits += [_extra(r).lstrip("; ")] if _extra(r) else []
    line = "; ".join(bits)
    return Section(lane, f"{heading} ({line})", line, kept, complete)


def _extra(r: LaneResult) -> str:
    names = {"labels_set_aside": "label{s} set aside"}
    out = []
    for k, v in (r.extra or {}).items():
        if v and k in names:
            out.append(f"{v} " + names[k].replace("{s}", "" if v == 1 else "s"))
    return "; " + "; ".join(out) if out else ""


# ---- what the model reads ------------------------------------------------------------------------

def render(m: Merged, question: str = "") -> str:
    """The sections, in priority order, each with its heading and a line saying how complete it is. The question goes last."""
    out = []
    for s in m.sections:
        lines = [s.heading + ":"]
        for it in s.items:
            lines.append(_render_item(it, question))
        out.append("\n".join(lines))
    if question:
        out.append(f"QUESTION: {question}")
    return "\n\n".join(out)


def _render_item(it: Item, question: str) -> str:
    also = f" (also found by: {', '.join(it.meta['also_found_in'])})" if it.meta.get("also_found_in") else ""
    if it.lane == "tables":
        where = f" part {it.part} of {it.parts}" + (f", rows {it.rows_from} to {it.rows_to} of {it.rows_total}" if it.rows_from is not None else "") if it.parts > 1 else ""
        body = it.text if it.parts > 1 else tableview.render(it.text, question)
        return f"  [{it.id}]{where}{also}\n{body}"
    return f"  [{it.id}]{also} {it.text}"
