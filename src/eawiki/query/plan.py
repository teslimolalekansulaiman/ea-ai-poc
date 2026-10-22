"""Query planner — the model decides the query TYPE and WHICH knowledge to load.

Given the question plus a catalog of what exists (subject pages + communities), an LLM
returns a plan: the type (pointed / relationship / summary / browse), the target
subject(s)/area(s) from the catalog, and the layers to load (blocks / graph / wiki /
landscape / full). This is the robust upgrade of the keyword router — the model tells
you what to pull, choosing only from things that actually exist.

For a small corpus you can skip this and load the whole wiki (executor `auto` mode);
the planner earns its place once the corpus is too big to load in full.
"""

from __future__ import annotations

import glob
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from eawiki.subjects import llm_json

PAGES = Path("data/pages")
GRAPH = Path("data/graph")
LOAD_LAYERS = {"blocks", "graph", "wiki", "landscape", "full"}
TYPES = {"pointed", "relationship", "summary", "browse"}


def _title(md: str, fallback: str) -> str:
    for line in md.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


@lru_cache(maxsize=1)
def catalog() -> dict:
    """The names the planner may target: subject pages + communities/areas."""
    subjects = []
    for fp in sorted(PAGES.glob("*.md")):
        if fp.name.startswith("landscape-"):
            continue
        subjects.append(_title(fp.read_text(encoding="utf-8"), fp.stem))
    communities = []
    cp = GRAPH / "communities.json"
    if cp.exists():
        communities = [c["name"] for c in json.loads(cp.read_text(encoding="utf-8")).get("communities", [])
                       if c.get("size", 0) >= 3]
    return {"subjects": subjects, "communities": communities}


def plan(question: str, backend: str = "cli", model: Optional[str] = None) -> dict:
    """Return {type, targets[], load[], reason}. Falls back to a safe default on error."""
    cat = catalog()
    prompt = (
        "Route this enterprise-architecture question. Decide its TYPE and WHICH knowledge to load. "
        "Output ONE JSON object.\n\n"
        "TYPES:\n"
        "  pointed      — a specific fact about one thing (owner, status, where stored)\n"
        "  relationship — impact / dependency / ownership / what connects to what\n"
        "  summary      — an overview of a topic, area, or the whole landscape\n"
        "  browse       — 'show me the page for X'\n\n"
        "LOAD layers (choose the minimal useful set): blocks (facts+citations), graph "
        "(relationships), wiki (a subject's synthesized page), landscape (a community's "
        "overview page), full (the entire wiki — only for broad whole-KB questions).\n\n"
        f"CATALOG — subjects you may target:\n{', '.join(cat['subjects'])}\n\n"
        f"CATALOG — communities/areas you may target:\n{', '.join(cat['communities'])}\n\n"
        f"QUESTION: \"{question}\"\n\n"
        "Guidance: pointed→[blocks,graph]; relationship→[graph,blocks]; summary of ONE subject→"
        "[wiki,blocks] with that subject in targets; summary of an AREA→[landscape] with that "
        "community in targets; broad/whole-KB→[full].\n"
        'Return: {"type":"<one>","targets":["<names from catalog>"],'
        '"load":["<layers>"],"reason":"<short>"}'
    )
    out = llm_json(prompt, backend, model)
    if not isinstance(out, dict):
        return {"type": "pointed", "targets": [], "load": ["blocks", "graph"], "reason": "planner fallback"}
    out["type"] = out.get("type") if out.get("type") in TYPES else "pointed"
    out["load"] = [x for x in (out.get("load") or []) if x in LOAD_LAYERS] or ["blocks", "graph"]
    out.setdefault("targets", [])
    return out
