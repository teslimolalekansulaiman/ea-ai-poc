"""The wiki pages that could answer a question, picked by title and first sentence and read for it.

The same search the case runs use (cases.pagefinder, cases.wikiread), asked with the user's own question: a model reads one line per
page (title, type, first sentence) and picks up to three; each picked page is read for the question (its summary and the sections that
bear on it). A model that gave no answer is reported as such, never as "no page fits".
"""

from __future__ import annotations

from typing import Callable, Optional

from eawiki.cases import pagefinder, wikiread

WORKERS = 4         # the parts of a long page list are asked at the same time


def pages_for(question: str, llm: Optional[Callable], kb, workers: int = WORKERS) -> dict:
    """{'state': 'picked'|'none'|'unread'|'no pages', 'offered': n, 'pages': [wikiread pages with digest and body], 'picked': [...]}"""
    found = pagefinder.find_pages(question, "", kb.wiki_entries(), llm, workers=workers)
    read = wikiread.read({"pages": found["picks"]}, kb.page, deep=question) if found["picks"] else {"pages": [], "status": {}}
    status = read["status"].get("pages", {})
    return {"state": found["state"], "offered": found["offered"], "unread_part": found["unread_part"], "pages": read["pages"],
            "picked": [{"name": c["name"], "slug": c["slug"], "state": status.get(c["id"], "not read")} for c in found["picks"]]}
