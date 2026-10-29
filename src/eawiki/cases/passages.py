"""Step 6 of the page finder: search the text of the ingested documents for what the lookup asks about a mention.

The question put to the search is the lookup's own question (written by the owner: "who owns each data set the demand
names") followed by what it is about: the mention, or for a lookup with no mention the opening words of the demand. A
search for the bare mention finds passages that resemble the word; one led by the question finds passages that answer
what the property is asking.

Where it looks: the documents the lookup names first, then a short search of every document, so a document added later,
or one the owner did not name, is never shut out. Each passage that comes back is marked for the mention it was
searched for:
  entry      its first words ARE the mention as written (a catalog row for it), or the name of a candidate step 1 to 3
             found for it (kind words aside: the candidate is a real entity of the kind the lookup accepts);
  mentioned  the name's words are in it but it is about something else ("payroll" inside the HR & Payroll Portal row);
  closest    neither: the nearest passages the search returned.
A search that returns nothing says so ("none"); a search that failed says "error": looked and found nothing is never
confused with could not look.

Pure: the search function (query, k, document ids) is passed in. In production it is the vector search; the tests use a
lexical stand-in, which exercises the plumbing and the marking, not the quality of embeddings.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Optional

from eawiki import lanes as lanes_mod
from eawiki.cases import namelookup as nl
from eawiki.cases import tableview

PER_MENTION = 3             # passages kept from the named documents per mention
PER_NEED = 5                # ... for a lookup with no mention (the demand as a whole)
GLOBAL_EXTRA = 2            # passages of ANY document added after the named ones
MAX_OFFICIAL = 2            # official names of the entities found for a mention that are searched as well
MAX_QUERY_TEXT = 500        # the demand's own words added to a lookup's question when it has no mention
HEAD_CHARS = 80             # an entry's name is at the start of its passage
FETCH_FACTOR = 3            # a lookup by meaning fetches this many times what it keeps, so label-only hits can be set behind real ones
MAX_EXPAND = 3              # label-only hits that are replaced by their neighbours, per search
RUN_WINDOW = 400            # blocks read after a label-only hit (the same section, up to the next heading)
CAPTION_CHARS = 160          # a short line with no sentence in it that sits next to a figure is read as the figure's caption
MAX_FIGURES = 3             # figures added for the captions among the hits
RUN_HEADER = 4              # the first cells of a long run are kept: they are the table's column names
RUN_AROUND = 2              # cells kept on each side of a cell that matches what was asked: its row
RUN_CHARS = 1800            # what follows a label, at most, as one passage
FRAGMENT_CHARS = 60
FRAGMENT_WORDS = 8
_ID = re.compile(r"\b[A-Za-z]{1,4}-\d+\b")


def passage_query(lookup: dict, mention: Optional[str], demand_text: str) -> str:
    """The question the search is asked: the lookup's question, then the mention (or the demand's opening words)."""
    find = str(lookup.get("find") or "").strip()
    if mention:
        return f"{find}: {mention}" if find else mention
    body = (demand_text or "")[:MAX_QUERY_TEXT]
    return f"{find}. {body}" if find else body


def head(text: str) -> str:
    """The start of a passage that names what it is about: its first sentence, at most HEAD_CHARS."""
    t = str(text or "").strip()
    m = re.search(r"[.!?:;\n]", t)
    return t[:min(m.start() if m else HEAD_CHARS, HEAD_CHARS)]


def names_head(passage_head: str, name: str) -> bool:
    """True when the passage's first words, set apart from any ID and any table cell, are exactly `name` (kind words
    aside). A head that merely CONTAINS the name ('HR & Payroll Portal' for 'payroll') is a partial name, not the name."""
    mc = nl.core(name)
    if not mc:
        return False
    cells = [passage_head] + re.split(r"\s*[|,]\s*", passage_head)
    return any(nl.core(_ID.sub(" ", c)) == mc for c in cells if c.strip())


def says_name(passage_head: str, mention: str) -> bool:
    """True when the passage's first words, set apart from any ID and any table cell, are exactly the mention INCLUDING its
    kind words: 'HR system' is not the row 'HR' (the data category), though both reduce to the same word without them."""
    mn = nl.norm(mention)
    cells = [passage_head] + re.split(r"\s*[|,]\s*", passage_head)
    return bool(mn) and any(nl.norm(_ID.sub(" ", c)) == mn for c in cells if c.strip())


def _words(s: str) -> set:
    return set(re.findall(r"[^\W_]{2,}", str(s or "").casefold()))


def _body(text: str) -> str:
    """A passage without the `document > section` line the index puts in front of it."""
    lines = str(text or "").strip().splitlines()
    if lines and " > " in lines[0]:
        lines = lines[1:]
    return "\n".join(lines).strip()


def is_fragment(block: dict) -> bool:
    """A hit that says nothing by itself: a table with a header and no row, or a few words with no sentence in them (a label,
    a column name, a heading kept as a paragraph). It matches almost any question that uses its word and answers none of them."""
    text = str(block.get("text") or "")
    if block.get("btype") == "table" or tableview.is_table(block):
        _, header, rows = tableview.parse(text)
        return len(rows) + (1 if header else 0) <= 1
    body = _body(text)
    if not re.search(r"\w", body):
        return True                                           # nothing but punctuation (a lone colon, a dash)
    return len(body) <= FRAGMENT_CHARS and len(body.split()) <= FRAGMENT_WORDS and not re.search(r"[.!?;:]", body)


def is_caption(block: dict) -> bool:
    """A short paragraph that is not a sentence ('Figure 8: Capability map: supporting - enabling'): what a caption looks like,
    in any language. Whether a figure is next to it decides if it is one."""
    if block.get("btype") in ("table", "figure", "heading") or is_fragment(block):
        return False
    body = _body(block.get("text", ""))
    return 0 < len(body) <= CAPTION_CHARS and not re.search(r"[.!?]\s*$", body) and "\n" not in body


def _figures_for(block: dict, expand_fn: Callable, seen: set) -> list[dict]:
    """The figure or table that a caption belongs to. A caption usually sits below its figure and above its table; so the figure before
    it comes first, then the table or figure after it, then a table before it. The diagram's description (or the table) is what the
    caption is about, and the caption is what a question about it finds."""
    try:
        near = expand_fn(block["block_id"], 1) or []
    except Exception:
        return []
    mine = block.get("ordinal")
    if mine is None:
        mine = next((r.get("ordinal") for r in near if r.get("block_id") == block["block_id"]), 0) or 0
    items = [n for n in near if n.get("btype") in ("figure", "table") and str(n.get("text") or "").strip()]
    before = [n for n in items if (n.get("ordinal") or 0) < mine][-1:]
    after = [n for n in items if (n.get("ordinal") or 0) > mine][:1]
    pick = [n for n in before if n.get("btype") == "figure"] or after or before
    return [{"block_id": n["block_id"], "doc_id": block.get("doc_id"), "btype": n["btype"], "section": n.get("section"),
             "text": n.get("text", ""), "via": block["block_id"], "figure": n["btype"] == "figure", "captioned": True,
             "distance": block.get("distance")} for n in pick if n.get("block_id") not in seen]


def _following(block: dict, near: list[dict]) -> list[dict]:
    """The blocks after `block` in its document and in the same section, in order: what a label labels. A heading starts another
    section, so the run ends there."""
    me = next((r for r in near if r.get("block_id") == block["block_id"]), None)
    start = ((me or block).get("ordinal") or 0)
    section = (me or block).get("section")
    run = []
    for n in sorted(near, key=lambda r: r.get("ordinal") or 0):
        if (n.get("ordinal") or 0) <= start:
            continue
        if n.get("btype") == "heading" or (section is not None and n.get("section") is not None and n.get("section") != section):
            break
        run.append(n)
    return run


def _pieces(run: list[dict]) -> list[tuple[str, bool]]:
    """What follows a label, block by block: (text, is a cell). A cell is a block of a few words (a table stored one cell per
    block); a real passage or table is kept whole."""
    out = []
    for n in run:
        piece = tableview.render(n.get("text", ""), "", RUN_CHARS) if (n.get("btype") == "table" or tableview.is_table(n)) else _body(n.get("text", ""))
        if piece:
            out.append((piece, is_fragment(n) and "\n" not in piece))
    return out


def _join(pieces: list[tuple[str, bool]], gaps: set) -> str:
    """Cells joined with ' | ', real passages on lines of their own; a gap (cells left out) is marked."""
    lines, cells = [], []
    def flush():
        if cells:
            lines.append(" | ".join(cells))
            cells.clear()
    for i, (text, is_cell) in enumerate(pieces):
        if i in gaps:
            cells.append("…") if is_cell else (flush(), lines.append("…"))
        if is_cell:
            cells.append(text)
        else:
            flush()
            lines.append(text)
    flush()
    return "\n".join(lines)


def _run_text(run: list[dict], query: str = "") -> str:
    """What follows a label, as one passage. When it is too long for RUN_CHARS it keeps the first cells (the column names) and,
    around every cell that shares the most distinctive words with what was asked (weighted by how few cells carry the word),
    that cell's row; with no match it keeps the start. What is left out is marked '…'."""
    pieces = _pieces(run)
    if sum(len(t) + 3 for t, _ in pieces) <= RUN_CHARS:
        return _join(pieces, set())
    q = tableview.words(query)
    n = len(pieces)
    df: dict = {}
    for t, _ in pieces:
        for w in tableview.words(t):
            df[w] = df.get(w, 0) + 1
    score = [sum(math.log(1 + n / df[w]) for w in q & tableview.words(t)) for t, _ in pieces]
    order = [i for i in sorted(range(n), key=lambda i: -score[i]) if score[i] > 0]
    chosen, used = set(range(min(RUN_HEADER, n))), sum(len(pieces[i][0]) + 3 for i in range(min(RUN_HEADER, n)))
    for i in order:
        around = [j for j in range(max(i - RUN_AROUND, 0), min(i + RUN_AROUND + 1, n)) if j not in chosen]
        cost = sum(len(pieces[j][0]) + 3 for j in around)
        if used + cost > RUN_CHARS:
            continue
        chosen |= set(around)
        used += cost
    if not order:                                              # nothing matches: the start of the run
        chosen, used = set(), 0
        for i in range(n):
            if used + len(pieces[i][0]) + 3 > RUN_CHARS:
                break
            chosen.add(i)
            used += len(pieces[i][0]) + 3
    keep = sorted(chosen)
    gaps = {keep[k] for k in range(1, len(keep)) if keep[k] != keep[k - 1] + 1}
    tail = "\n(the rest follows in the document)" if keep and keep[-1] < n - 1 else ""
    return _join([pieces[i] for i in keep], {k for k, i in enumerate(keep) if i in gaps}) + tail


def reshape(hits: list[dict], k: int, expand_fn: Optional[Callable] = None, query: str = "") -> tuple[list[dict], int, int]:
    """For a search by meaning: the real passages, without the label-only ones, and each of the first few label-only hits is
    followed by what comes after it in its document, as one passage
    marked `via` (a table stored one cell per block comes back as its cells in order). Returns (passages, label-only hits
    seen, passages added)."""
    outside = [b for b in hits if b.get("outside")]
    named = [b for b in hits if not b.get("outside")]
    frag = [b for b in named if is_fragment(b)]
    keep = [b for b in named if b not in frag][:k]          # a bare label is not kept to fill the list: it says nothing, and what follows it is read instead
    seen = {b["block_id"] for b in keep + outside}
    added: list[dict] = []
    covered: set = set()
    if expand_fn:
        for b in frag[:MAX_EXPAND]:
            if b["block_id"] in covered:
                continue                                  # already read as part of an earlier label's run
            try:
                run = _following(b, expand_fn(b["block_id"], RUN_WINDOW) or [])
            except Exception:
                run = []
            text = _run_text(run, query)
            covered |= {n["block_id"] for n in run}
            free = [n for n in run if n.get("block_id") not in seen]      # the passage is cited by its first block that is not already a hit
            if not text or not free:
                continue
            head = f"{b.get('doc_id') or ''} > {run[0].get('section') or b.get('section') or ''}".strip(" >")
            added.append({"block_id": free[0]["block_id"], "doc_id": b.get("doc_id"), "btype": "paragraph", "section": run[0].get("section"),
                          "text": f"{head}\n{text}", "via": b["block_id"], "run_to": run[-1]["block_id"], "distance": b.get("distance")})
            seen.add(free[0]["block_id"])
    if expand_fn:
        for b in keep:
            if len([a for a in added if a.get("captioned")]) >= MAX_FIGURES:
                break
            if is_caption(b):
                for f in _figures_for(b, expand_fn, seen):
                    seen.add(f["block_id"])
                    added.append(f)
    read_from = {a["via"] for a in added if not a.get("captioned")}          # a label whose run was read says nothing more than its run does
    keep = [b for b in keep if b["block_id"] not in read_from]
    return keep + added + outside, len(frag), len(added)


_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+")


def _heading_of(block: dict) -> str:
    """The heading a passage sits under: the last part of its section path (a number in front of it removed). In a document
    that gives every item a section of its own ('4.29 Evaluate') this is where the item's NAME is, and a table or paragraph
    under it describes it without repeating it."""
    sec = str(block.get("section") or "")
    if not sec:
        first = str(block.get("text") or "").strip().splitlines()[:1]
        sec = first[0].split(" > ", 1)[1] if first and " > " in first[0] else ""
    return _NUMBER.sub("", sec.split(" / ")[-1]).strip()


def mark(blocks: list[dict], mention: str, candidate_names: Optional[list] = None) -> dict:
    """{'entry': [block ids], 'mentioned': [...], 'closest': [...]} for the passages found for one mention."""
    want = _words(mention)
    entry, mentioned, closest = [], [], []
    for b in blocks:
        body = _body(b.get("text", ""))                    # the `document > section` line the index puts in front is not what the passage says
        h = head(body)
        # a candidate's name is a real entity's name (kind words aside); the mention itself must match as written
        under = _heading_of(b) if not is_fragment(b) else ""         # a real passage under a heading that IS the name describes that item
        if says_name(h, mention) or any(names_head(h, n) for n in (candidate_names or []) if n) or \
                (under and (says_name(under, mention) or any(names_head(under, n) for n in (candidate_names or []) if n))):
            entry.append(b["block_id"])
        elif want and want <= _words(body):
            mentioned.append(b["block_id"])
        else:
            closest.append(b["block_id"])
    return {"entry": entry, "mentioned": mentioned, "closest": closest}


def search(search_fn: Callable, query: str, k: int, docs: list, strict: bool = False, types: Optional[list] = None) -> list[dict]:
    """The named documents first; then, unless `strict`, a short search of everything. A passage found only by the
    second search carries outside=True. `types` limits the search to block types (a lane). A hit is told apart by its block AND its part:
    parts 2 and 3 of one table are two hits."""
    out, seen = [], set()
    ask = (lambda q, n, d: search_fn(q, n, d, types)) if types else search_fn
    for b in (ask(query, k, docs) if docs else ask(query, k, None)) or []:
        key = (b["block_id"], b.get("part", 1))
        if key not in seen:
            seen.add(key)
            out.append(dict(b))
    if docs and not strict:
        for b in ask(query, GLOBAL_EXTRA, None) or []:
            key = (b["block_id"], b.get("part", 1))
            if key not in seen:
                seen.add(key)
                out.append(dict(b, outside=True))
    return out


def read(lookup: dict, mentions: list, demand_text: str, search_fn: Callable, candidates: Optional[dict] = None,
         strict: bool = False, expand_fn: Optional[Callable] = None, lanes_k: Optional[dict] = None) -> dict:
    """Run one lookup's search. `mentions`: the names to look up ([None] for the demand as a whole; [] when the demand names nothing of this kind: no search); `candidates`:
    {mention: [candidate dicts with 'name'] } from steps 1 to 3. Returns {'items': [per mention], 'blocks': [...]}.
    item: {'mention', 'query', 'queries' (every question asked), 'by' ('name'|'meaning'), 'state' ('found'|'none'|'error'),
    'entry', 'mentioned', 'closest'}."""
    docs = list(lookup.get("docs") or [])
    items, blocks, seen = [], [], set()
    for m in (mentions if mentions is not None else [None]):          # [] = the demand names nothing of this kind: nothing is searched
        q = passage_query(lookup, m, demand_text)
        by = "name" if m and lookup.get("match") == "name" else "meaning"
        # The mention may be an abbreviation or another wording of what the documents call by its official name ("CRM"):
        # the entities found for it (strong matches and the page finder's picks) are searched by their names too.
        official = [c["name"] for c in (candidates or {}).get(m, []) if c.get("strong") or str(c.get("how", "")).startswith("chosen")]
        extra = [n for n in dict.fromkeys(official) if nl.norm(n) != nl.norm(m or "")][:MAX_OFFICIAL] if by == "name" else []
        try:
            k = PER_MENTION if m else PER_NEED
            fragments = added = 0
            if lanes_k and by == "meaning":
                # the retrieval merge: tables, figures and text are searched each on its own, so a label cannot push a table or a diagram out
                text_hits = search(search_fn, q, lanes_k.get("text", k) * FETCH_FACTOR, docs, strict, list(lanes_mod.types_of("text")))
                text_hits, fragments, added = reshape(text_hits, lanes_k.get("text", k), expand_fn, q)
                seen_keys = {(b["block_id"], b.get("part", 1)) for b in text_hits}
                hits = list(text_hits)
                for lane in ("tables", "figures"):
                    for b in search(search_fn, q, lanes_k.get(lane, 2), docs, strict, list(lanes_mod.types_of(lane))):
                        if (b["block_id"], b.get("part", 1)) not in seen_keys:
                            seen_keys.add((b["block_id"], b.get("part", 1)))
                            hits.append(b)
            else:
                hits = search(search_fn, q, k * FETCH_FACTOR, docs, strict)
                if by == "meaning":
                    hits, fragments, added = reshape(hits, k, expand_fn, q)
            for n in extra:
                have = {b["block_id"] for b in hits}
                hits += [b for b in search(search_fn, passage_query(lookup, n, demand_text), PER_MENTION, docs, strict) if b["block_id"] not in have]
        except Exception:
            items.append({"mention": m, "query": q, "queries": [q], "by": by, "state": "error", "entry": [], "mentioned": [], "closest": []})
            continue
        marks = mark(hits, m, [c["name"] for c in (candidates or {}).get(m, [])]) if by == "name" else \
            {"entry": [], "mentioned": [], "closest": [b["block_id"] for b in hits]}
        if by == "name":
            # a label ("Hosting", "Supplier name") that is neither the entry for the name nor mentions it says nothing about it
            labels = {b["block_id"] for b in hits if b["block_id"] in set(marks["closest"]) and is_fragment(b)}
            fragments = len(labels)
            hits = [b for b in hits if b["block_id"] not in labels]
            hits = [b for b in hits if not b.get("outside")][:k] + [b for b in hits if b.get("outside")]       # what was fetched beyond k to make up for the labels
            kept = {b["block_id"] for b in hits}
            marks = {key: [i for i in v if i in kept] for key, v in marks.items()}
        items.append({"mention": m, "query": q, "queries": [q] + [passage_query(lookup, n, demand_text) for n in extra], "by": by,
                      "state": "found" if hits else "none", "fragments": fragments, "expanded": added, **marks})
        for b in hits:
            key = (b["block_id"], b.get("part", 1))
            if key not in seen:
                seen.add(key)
                blocks.append(b)
    return {"items": items, "blocks": blocks}
