"""Route a question to a retrieval strategy.

Rule-based to start (fast, transparent, no model call). The LLM can take over the
routing later by swapping `route()` for a Pulse classification — same return shape.

Strategies:
  vector  — local / pointed question -> embed + nearest blocks (default)
  graph   — dependency / impact / ownership / "what connects to X" -> traverse the graph
  global  — cross-cutting / summary / landscape -> community layer (Steps 7-9, later)
  browse  — "show me the page for X" -> fetch the entity's page/subgraph
"""

from __future__ import annotations

GRAPH_HINTS = ("depend", "impact", "affect", "connect", "who owns", "owned by",
               "upstream", "downstream", "integrat", "talks to", "uses ", "used by",
               "relationship", "related to")
GLOBAL_HINTS = ("summar", "overview", "landscape", "across", "overall", "how many",
                "coverage", "all the", "map of", "big picture")
BROWSE_HINTS = ("show me the page", "page for", "tell me about", "what is the")


def route(question: str) -> dict:
    q = question.lower().strip()
    if any(h in q for h in GLOBAL_HINTS):
        return {"strategy": "global", "reason": "cross-cutting / summary wording"}
    if any(h in q for h in GRAPH_HINTS):
        return {"strategy": "graph", "reason": "dependency / relationship wording"}
    if any(h in q for h in BROWSE_HINTS):
        return {"strategy": "browse", "reason": "asks to browse a specific subject"}
    return {"strategy": "vector", "reason": "default: pointed/local question"}
