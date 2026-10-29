"""Assemble grounded context and produce an answer with citations.

The LLM call routes through `subjects.llm_text(prompt, backend, model)` — the single
place every model call in this repo goes — so pointing it at Pulse is one change there,
not here. The answer is instructed to cite block ids and to say when the context is
insufficient (grounding / anti-hallucination).
"""

from __future__ import annotations

from typing import Optional

from eawiki.subjects import llm_text


def assemble_context(blocks: list[dict], subgraph: Optional[dict] = None, query: str = "") -> str:
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
        via = b.get("via")
        note = ("" if not via else f" (the diagram that the caption [{via}] belongs to; this is its description)" if b.get("figure")
                else f" (the table that the caption [{via}] belongs to)" if b.get("captioned")
                else f" (what follows [{via}] in its document, which was only a label)")
        text = (b.get("text") or "").strip()
        if b.get("btype") == "table":          # a long table is shown tidied, with the rows that bear on the question (as in the case runs)
            from eawiki.cases import tableview
            text = tableview.render(text, query)
        lines.append(f"[{cite}] ({sect}){note}\n{text}")
    return "\n".join(lines)


def build_prompt(question: str, context: str, history: Optional[list] = None) -> str:
    convo = ""
    if history:
        turns = "\n".join(f"{h.get('role')}: {h.get('content')}" for h in history[-6:])
        convo = ("Conversation so far (for reference and pronoun resolution only — do not "
                 "treat it as a source to cite):\n" + turns + "\n\n")
    return f"""Answer the question using ONLY the context below (source blocks, graph facts and wiki pages). Cite the block id in square brackets after each claim, like [03-data:5]; cite a wiki page by its id, like [wiki:payroll-portal]. Do not invent facts, and make no statement you cannot cite.

Say what you found in whichever of these three ways is true, and no other:
1. STATED in the context: say it plainly, with its citation. Do not hedge it, and do not say the context "does not explicitly" or "does not exactly" state it.
2. WORKED OUT from more than one piece of the context (a table row and a wiki page, rows spread over several parts of a table, a diagram and its caption): give the answer, then say what it rests on, for example "Based on [a] and [b], ...". That is the basis of the answer, not an apology; it is cited, so do not call it missing, partial or uncertain.
3. NOT in the context: say so once, briefly, and in a few words where it was looked (for example "the capability table, the diagrams and the wiki pages"); do not list blocks. Answer any part of the question the context does answer, and say only what remains unanswered. Do not follow it with a guess written as a fact.

Where a section heading says how complete it is ("3 shown", "none found", "parts 6 to 8 of 8 shown"), believe it. A complete section holds everything that was found, so do not apologise for what it holds. Say something is missing only when a section says it is partial, "could not be searched" or "not searched", and then name that section. "none found" means it was searched and nothing was there; "could not be searched" means nothing can be concluded from it.

{convo}Question: {question}

Context:
{context}

Answer (grounded, with [block] citations):"""


def answer(question: str, context: str, backend: str = "cli",
           model: Optional[str] = None, history: Optional[list] = None) -> str:
    """One grounded answer. `backend` is the model backend (cli today; pulse later)."""
    return llm_text(build_prompt(question, context, history), backend, model).strip()
