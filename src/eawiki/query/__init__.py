"""Query-time layer for the EA GraphRAG wiki (serving side).

Separate from the build pipeline (eawiki.parse/tables/.../load). Small, explicit
Python — no agent framework — because the flow is route -> retrieve -> answer, a
short DAG. If it ever becomes a genuine agent (iterative retrieval, self-correction)
these functions can be wrapped in LangGraph without rewriting them.

Capabilities (plain functions/classes) that use cases / skills call:
  retrieve.Retriever  — vector search + graph traversal over ArcadeDB
  route.route         — classify a question into a retrieval strategy
  answer.answer       — assemble grounded context + LLM answer with citations
  ask                 — one entry point (CLI): python -m eawiki.query.ask "..."
"""
