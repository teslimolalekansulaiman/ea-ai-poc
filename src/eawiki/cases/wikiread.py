"""Step 4 of the page finder: read the wiki page of each candidate. Plain code, no model.

The pages are written when the documents are ingested (src/eawiki/pages.py) and come in three shapes, none of
which has fixed headings, so the digest does not rely on any:
  * a model-written page: "# Name", then prose that starts with what the thing is, bullets, inline citations
    such as [03-data:5], and headings of the model's own choosing;
  * a table-only item's page built in code: "# Name", an italic "*type* - listed in ... [block]" line,
    then "## Attributes" and "## Relationships" bullets;
  * an item listed only on a catalogue page: no page of its own; the caller passes that item's section as markdown.

The digest is the title, the type if the page states it, the summary, the rest of the opening prose (what it is) and the
bullets (attributes and relationships), each cut to a size. Inline citations are removed from the text: they point at
passages this step did not show, and an answer may cite only what it was shown. The page itself is cited as
`wiki:<slug>`.

A page that cannot be read is reported as such ("error"), never as "no page".
"""

from __future__ import annotations

import re
from typing import Callable, Optional

MAX_PER_MENTION = 3        # candidates per mention whose page is read, best first
MAX_PAGES = 8              # pages kept for one property
# Headings the page generator's own prompt asks for ("a summary, what it is, ..."): prose under one of these leads the digest.
PREFERRED = ("what it is", "overview", "description", "about")
SUMMARY_CHARS = 450
LEAD_CHARS = 450
FACT_CHARS = 900
FACT_EACH = 300           # one bullet is cut here: the neighbours' names come first in a relationship bullet
MAX_FACTS = 12

# A citation is a block id, "<document>:<number>", in brackets or bare, possibly several run together. The document part
# contains an underscore or a hyphen, so "10:30" and "3:1" are not citations.
_BLOCK = r"[\w][\w.\-]*[_\-][\w.\-]*:\d+"
_LOOSE = r"[\w][\w.\-]*:\d+"                 # inside brackets any document name is taken as a citation
_CITE = re.compile(rf"\s*\[{_LOOSE}(?:\s*[,;]\s*{_LOOSE})*\]|\s*(?<![A-Za-z_\-]){_BLOCK}")
_ITALIC_TYPE = re.compile(r"^\*([^*]+)\*\s*(?:[-—–\[]|$)")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+\.)\s+(.*\S)")


def evidence_id(slug: str) -> str:
    return f"wiki:{slug}"


def strip_citations(text: str) -> str:
    return _CITE.sub("", text or "").strip()


def digest_page(md: str, summary_chars: int = SUMMARY_CHARS, lead_chars: int = LEAD_CHARS, fact_chars: int = FACT_CHARS) -> dict:
    """{'title', 'type', 'summary', 'summary_from', 'lead', 'facts', 'empty'}.
    summary: the page's own "Summary" section; when the page has none, its first paragraph, and `summary_from` says
    which ("page" | "first paragraph" | ""), so a page written without a summary can be seen and fixed at the source.
    lead: the rest of what the page says it is (prose under "What it is" and the like first, then the other prose)."""
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
    summary, first, rest, heading = [], [], [], ""
    for ln in lines:
        t = ln.strip()
        if t.startswith("#"):
            heading = t.lstrip("#").strip().lower()
            continue
        if not t or _BULLET.match(t) or _ITALIC_TYPE.match(t) or t.lower().startswith("type:"):
            continue
        t = strip_citations(t)
        if not t or t == title:                      # the page's own name repeated under its title is not prose
            continue
        if heading == "summary":
            summary.append(t)
        else:
            (first if heading in PREFERRED else rest).append(t)
    summary_from = "page" if summary else ""
    prose = first + rest
    if not summary and prose:                        # no Summary section: the first paragraph stands in, and says so
        summary, summary_from = [prose[0]], "first paragraph"
        prose = prose[1:]
    lead, size = [], 0
    for t in prose:                                  # what the page says it is first; nothing is left out, only ordered
        lead.append(t)
        size += len(t) + 1
        if size >= lead_chars:
            break
    facts = []
    for ln in lines:
        m = _BULLET.match(ln)
        if m:
            facts.append(strip_citations(m.group(1))[:FACT_EACH])
        if len(facts) == MAX_FACTS:
            break
    facts_text = "; ".join(f for f in facts if f)
    out = {"title": title, "type": typ, "summary": " ".join(summary)[:summary_chars].strip(), "summary_from": summary_from,
           "lead": " ".join(lead)[:lead_chars].strip(), "facts": facts_text[:fact_chars].strip()}
    out["empty"] = not (out["summary"] or out["lead"] or out["facts"])
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
