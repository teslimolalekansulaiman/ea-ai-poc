"""Assemble grounded context and produce an answer with citations.

The LLM call routes through `subjects.llm_text(prompt, backend, model)` — the single
place every model call in this repo goes — so pointing it at Pulse is one change there,
not here. The answer is instructed to cite block ids and to say when the context is
insufficient (grounding / anti-hallucination).
"""

from __future__ import annotations

from typing import Optional

from eawiki.subjects import llm_text


def assemble_context(blocks: list[dict], subgraph: Optional[dict] = None) -> str:
    """Render retrieved blocks (+ optional graph facts) as the model's evidence."""
    lines: list[str] = []
    if subgraph and (subgraph.get("out") or subgraph.get("in")):
        lines.append("GRAPH FACTS:")
        for e in subgraph.get("out", []):
            lines.append(f"  {subgraph['node_id']} --{e.get('relation')}--> {e.get('target')}")
        for e in subgraph.get("in", []):
            lines.append(f"  {e.get('source')} --{e.get('relation')}--> {subgraph['node_id']}")
        lines.append("")
    lines.append("SOURCE BLOCKS:")
    for b in blocks:
        cite = b.get("block_id", "?")
        sect = b.get("section") or ""
        lines.append(f"[{cite}] ({sect})\n{(b.get('text') or '').strip()}")
    return "\n".join(lines)


def build_prompt(question: str, context: str) -> str:
    return f"""Answer the question using ONLY the context below (source blocks + any graph facts). Cite the block id in square brackets after each claim, like [03-data:5]. If the context does not contain the answer, say so plainly — do not invent facts.

Question: {question}

Context:
{context}

Answer (grounded, with [block] citations):"""


def answer(question: str, context: str, backend: str = "cli",
           model: Optional[str] = None) -> str:
    """One grounded answer. `backend` is the model backend (cli today; pulse later)."""
    return llm_text(build_prompt(question, context), backend, model).strip()
