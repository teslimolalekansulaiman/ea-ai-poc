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

import re
from typing import Callable, Optional

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
PER_FRAGMENT = 2            # neighbours taken for one label-only hit
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
    return len(body) <= FRAGMENT_CHARS and len(body.split()) <= FRAGMENT_WORDS and not re.search(r"[.!?;:]", body)


def reshape(hits: list[dict], k: int, expand_fn: Optional[Callable] = None) -> tuple[list[dict], int, int]:
    """For a search by meaning: real passages before label-only ones (those fill the list only when there are too few real
    ones), and each of the first few label-only hits is followed by the passages next to it in its document, marked `via`.
    Returns (passages, label-only hits seen, neighbours added)."""
    outside = [b for b in hits if b.get("outside")]
    named = [b for b in hits if not b.get("outside")]
    frag = [b for b in named if is_fragment(b)]
    keep = [b for b in named if b not in frag][:k]
    keep += frag[:max(k - len(keep), 0)]
    seen = {b["block_id"] for b in keep + outside}
    added: list[dict] = []
    if expand_fn:
        for b in frag[:MAX_EXPAND]:
            try:
                near = expand_fn(b["block_id"], 2) or []
            except Exception:
                near = []
            took = 0
            for n in sorted(near, key=lambda r: r.get("ordinal") or 0):
                if n.get("block_id") in seen or took >= PER_FRAGMENT or n.get("block_id") == b["block_id"]:
                    continue
                cand = {"block_id": n["block_id"], "doc_id": b.get("doc_id"), "btype": n.get("btype"), "section": n.get("section"),
                        "text": n.get("text", ""), "via": b["block_id"]}
                if is_fragment(cand) or (n.get("ordinal") or 0) < (next((r.get("ordinal") for r in near if r.get("block_id") == b["block_id"]), 0) or 0):
                    continue                          # what follows a label is what it labels
                seen.add(cand["block_id"])
                added.append(cand)
                took += 1
    return keep + added + outside, len(frag), len(added)


def mark(blocks: list[dict], mention: str, candidate_names: Optional[list] = None) -> dict:
    """{'entry': [block ids], 'mentioned': [...], 'closest': [...]} for the passages found for one mention."""
    want = _words(mention)
    entry, mentioned, closest = [], [], []
    for b in blocks:
        h = head(b.get("text", ""))
        # a candidate's name is a real entity's name (kind words aside); the mention itself must match as written
        if says_name(h, mention) or any(names_head(h, n) for n in (candidate_names or []) if n):
            entry.append(b["block_id"])
        elif want and want <= _words(b.get("text", "")):
            mentioned.append(b["block_id"])
        else:
            closest.append(b["block_id"])
    return {"entry": entry, "mentioned": mentioned, "closest": closest}


def search(search_fn: Callable, query: str, k: int, docs: list, strict: bool = False) -> list[dict]:
    """The named documents first; then, unless `strict`, a short search of everything. A passage found only by the
    second search carries outside=True."""
    out, seen = [], set()
    for b in (search_fn(query, k, docs) if docs else search_fn(query, k, None)) or []:
        if b["block_id"] not in seen:
            seen.add(b["block_id"])
            out.append(dict(b))
    if docs and not strict:
        for b in search_fn(query, GLOBAL_EXTRA, None) or []:
            if b["block_id"] not in seen:
                seen.add(b["block_id"])
                out.append(dict(b, outside=True))
    return out


def read(lookup: dict, mentions: list, demand_text: str, search_fn: Callable, candidates: Optional[dict] = None,
         strict: bool = False, expand_fn: Optional[Callable] = None) -> dict:
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
            hits = search(search_fn, q, k * FETCH_FACTOR if by == "meaning" else k, docs, strict)
            fragments = added = 0
            if by == "meaning":
                hits, fragments, added = reshape(hits, k, expand_fn)
            for n in extra:
                have = {b["block_id"] for b in hits}
                hits += [b for b in search(search_fn, passage_query(lookup, n, demand_text), PER_MENTION, docs, strict) if b["block_id"] not in have]
        except Exception:
            items.append({"mention": m, "query": q, "queries": [q], "by": by, "state": "error", "entry": [], "mentioned": [], "closest": []})
            continue
        marks = mark(hits, m, [c["name"] for c in (candidates or {}).get(m, [])]) if by == "name" else \
            {"entry": [], "mentioned": [], "closest": [b["block_id"] for b in hits]}
        items.append({"mention": m, "query": q, "queries": [q] + [passage_query(lookup, n, demand_text) for n in extra], "by": by,
                      "state": "found" if hits else "none", "fragments": fragments, "expanded": added, **marks})
        for b in hits:
            if b["block_id"] not in seen:
                seen.add(b["block_id"])
                blocks.append(b)
    return {"items": items, "blocks": blocks}
