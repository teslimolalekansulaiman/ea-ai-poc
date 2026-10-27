"""Step 4 of the page finder: read the wiki page of each candidate. Plain code, no model.

The pages are written when the documents are ingested (src/eawiki/pages.py) and come in three shapes, none of
which has fixed headings, so the digest does not rely on any:
  * a model-written page: "# Name", then prose that starts with what the thing is, bullets, inline citations
    such as [03-data:5], and headings of the model's own choosing;
  * a table-only item's page built in code: "# Name", an italic "*type* - listed in ... [block]" line,
    then "## Attributes" and "## Relationships" bullets;
  * an item listed only on a catalogue page: no page of its own; the caller passes that item's section as markdown.

The digest is the title, the type if the page states it, the opening prose (what it is) and the bullets
(attributes and relationships), cut to a size. Inline citations are removed from the text: they point at
passages this step did not show, and an answer may cite only what it was shown. The page itself is cited as
`wiki:<slug>`.

A page that cannot be read is reported as such ("error"), never as "no page".
"""

from __future__ import annotations

import re
from typing import Callable, Optional

MAX_PER_MENTION = 3        # candidates per mention whose page is read, best first
MAX_PAGES = 8              # pages kept for one property
LEAD_CHARS = 700
FACT_CHARS = 700
MAX_FACTS = 12

_CITE = re.compile(r"\s*\[(?:[^\[\]\s:,]+:\d+)(?:\s*[,;]\s*[^\[\]\s:,]+:\d+)*\]")
_ITALIC_TYPE = re.compile(r"^\*([^*]+)\*\s*(?:[-—–\[]|$)")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+\.)\s+(.*\S)")


def evidence_id(slug: str) -> str:
    return f"wiki:{slug}"


def strip_citations(text: str) -> str:
    return _CITE.sub("", text or "").strip()


def digest_page(md: str, lead_chars: int = LEAD_CHARS, fact_chars: int = FACT_CHARS) -> dict:
    """{'title', 'type', 'lead', 'facts', 'empty'}. `type` is what the page itself says ("" if it says nothing)."""
    lines = [ln.rstrip() for ln in (md or "").splitlines()]
    title = next((ln.lstrip("#").strip() for ln in lines if ln.startswith("# ")), "")
    typ = ""
    for ln in lines[:10]:
        m = _ITALIC_TYPE.match(ln.strip())
        if m:
            typ = m.group(1).strip()
            break
        if ln.strip().lower().startswith("type:"):
            typ = ln.split(":", 1)[1].strip()
            break
    lead, size = [], 0
    for ln in lines:
        t = ln.strip()
        if not t or t.startswith("#") or _BULLET.match(t) or _ITALIC_TYPE.match(t) or t.lower().startswith("type:"):
            continue
        t = strip_citations(t)
        if not t:
            continue
        lead.append(t)
        size += len(t) + 1
        if size >= lead_chars:
            break
    facts = []
    for ln in lines:
        m = _BULLET.match(ln)
        if m:
            facts.append(strip_citations(m.group(1)))
        if len(facts) == MAX_FACTS:
            break
    facts_text = "; ".join(f for f in facts if f)
    out = {"title": title, "type": typ, "lead": " ".join(lead)[:lead_chars].strip(), "facts": facts_text[:fact_chars].strip()}
    out["empty"] = not (out["lead"] or out["facts"])
    return out


def read(by_mention: dict, page_fn: Callable[[str], Optional[str]], per_mention: int = MAX_PER_MENTION, total: int = MAX_PAGES) -> dict:
    """by_mention: {mention: [candidate, ...]} best first; a candidate has id, name, type, how and (when it has one) slug.
    Returns {'pages': [{'id','slug','name','type','how','digest'}], 'status': {mention: {candidate id: state}}}.
    state: 'read' | 'no page' (the candidate has none) | 'error' (the page could not be read) | 'not read' (over the limit)."""
    pages: dict = {}
    status: dict = {}
    for mention, cands in by_mention.items():
        status[mention] = {}
        for i, c in enumerate(cands):
            slug = c.get("slug")
            if i >= per_mention:
                status[mention][c["id"]] = "not read"
                continue
            if not slug:
                status[mention][c["id"]] = "no page"
                continue
            if slug in pages:
                status[mention][c["id"]] = "read"
                continue
            if len(pages) >= total:
                status[mention][c["id"]] = "not read"
                continue
            try:
                md = page_fn(slug)
            except Exception:
                status[mention][c["id"]] = "error"
                continue
            if not md or not str(md).strip():
                status[mention][c["id"]] = "no page"
                continue
            pages[slug] = {"id": evidence_id(slug), "slug": slug, "name": c["name"], "type": c.get("type", ""), "how": c.get("how", ""),
                           "digest": digest_page(md)}
            status[mention][c["id"]] = "read"
    return {"pages": list(pages.values()), "status": status}
